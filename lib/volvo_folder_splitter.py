#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Volvo XC70 2012 USB Folder File-Count Splitter

The Volvo stereo supports at most 254 files per folder. This script finds
folders that exceed the limit and splits them into numbered subfolders.

Files are sorted alphabetically and divided into groups of at most
--group-size files (default 200, leaving headroom below the 254 limit).

Example
-------
  Before: music/Phish/  (400 files)
  After:  music/Phish/01 (A-L)/  (200 files)
          music/Phish/02 (M-Z)/  (200 files)

Run this BEFORE the main pipeline verify step, or re-run the verifier
afterwards so the pipeline picks up the new folder structure.

Dry-run by default. Pass --apply to move files.

Writes logs/volvo_split_manifest_YYYYMMDD_HHMMSS.csv.
"""

import csv
import logging
import math
import os
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from logging_utils import configure_file_logger, resolve_run_output_dir
except ImportError:
    from lib.logging_utils import configure_file_logger, resolve_run_output_dir

if sys.platform == "win32":
    import io
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


MAX_FILES_PER_FOLDER = 254
DEFAULT_GROUP_SIZE = 200
SUPPORTED_EXTENSIONS = {'.mp3', '.wma', '.aac', '.m4a', '.m4b'}


class VolvoFolderSplitter:
    """Splits overcrowded folders into alphabetical numbered subgroups."""

    def __init__(self, drive_path: str, dry_run: bool = True,
                 group_size: int = DEFAULT_GROUP_SIZE,
                 manifest_file: Optional[str] = None):
        self.drive_path = Path(drive_path)
        self.dry_run = dry_run
        self.group_size = group_size
        self.manifest_file = Path(manifest_file) if manifest_file else None
        self.logger = logging.getLogger('VolvoFolderSplitter')
        self.manifest_rows: List[Dict] = []
        self.stats: Dict[str, int] = defaultdict(int)

    def log(self, message: str):
        print(message)
        self.logger.info(message)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def find_overcrowded(self) -> Dict[Path, List[Path]]:
        """Return {folder: sorted_audio_files} for each folder over the limit."""
        overcrowded: Dict[Path, List[Path]] = {}
        for root, _dirs, files in os.walk(self.drive_path):
            root_path = Path(root)
            audio = sorted(
                [root_path / f for f in files
                 if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS],
                key=lambda p: p.name.lower(),
            )
            if len(audio) > MAX_FILES_PER_FOLDER:
                overcrowded[root_path] = audio
        return overcrowded

    # ------------------------------------------------------------------
    # Splitting strategy
    # ------------------------------------------------------------------

    def plan_splits(self, audio_files: List[Path]) -> List[Tuple[str, List[Path]]]:
        """Return [(group_name, files)] for one overcrowded folder.

        Files are already sorted alphabetically. Groups are numbered 01, 02 …
        and annotated with the first-letter range of files they contain.
        """
        groups: List[Tuple[str, List[Path]]] = []
        for i, start in enumerate(range(0, len(audio_files), self.group_size)):
            chunk = audio_files[start:start + self.group_size]
            first = chunk[0].stem[0].upper() if chunk[0].stem else '0'
            last = chunk[-1].stem[0].upper() if chunk[-1].stem else 'Z'
            label = (f"{i + 1:02d} ({first})"
                     if first == last
                     else f"{i + 1:02d} ({first}-{last})")
            groups.append((label, chunk))
        return groups

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def split_all(self):
        mode = "DRY RUN" if self.dry_run else "LIVE MODE"
        self.log(f"\n{'=' * 70}")
        self.log(f"Volvo Folder Splitter - {mode}")
        self.log(f"{'=' * 70}")

        if self.dry_run:
            self.log("\n⚠ DRY RUN: No files will be moved. Use --apply to split folders.")
        else:
            self.log("\n⚠ LIVE MODE: Files will be moved into subfolders!")

        self.log(f"\nScanning for folders with >{MAX_FILES_PER_FOLDER} audio files...")
        overcrowded = self.find_overcrowded()

        if not overcrowded:
            self.log(
                f"\n✓ No overcrowded folders found. "
                f"All folders are within the {MAX_FILES_PER_FOLDER}-file limit."
            )
            self.write_manifest()
            return

        self.log(f"\nFound {len(overcrowded)} overcrowded folder(s):\n")

        for folder, audio_files in sorted(overcrowded.items()):
            rel_folder = self._rel(folder)
            splits = self.plan_splits(audio_files)
            verb = "Would split" if self.dry_run else "Splitting"
            self.log(
                f"  {verb}: {rel_folder}/ "
                f"({len(audio_files)} files → {len(splits)} subfolders)"
            )
            for group_name, chunk in splits:
                first30 = chunk[0].name[:30]
                last30 = chunk[-1].name[:30]
                self.log(f"    {group_name}/  ({len(chunk)} files: {first30}…{last30})")

            if not self.dry_run:
                for group_name, chunk in splits:
                    target_dir = folder / group_name
                    target_dir.mkdir(exist_ok=True)
                    for src in chunk:
                        dst = target_dir / src.name
                        try:
                            shutil.move(str(src), str(dst))
                            self.stats['files_moved'] += 1
                            self._record(self._rel(src), self._rel(dst), 'moved')
                        except Exception as exc:
                            self.stats['errors'] += 1
                            self._record(self._rel(src), '', 'error', str(exc))
                            self.log(f"      ERROR moving {src.name}: {exc}")
                    self.stats['groups_created'] += 1
            else:
                for group_name, chunk in splits:
                    target_dir = folder / group_name
                    for f in chunk:
                        self._record(
                            self._rel(f),
                            self._rel(target_dir / f.name),
                            'would_move',
                        )
                self.stats['would_split'] += 1

        self.write_manifest()
        self.print_summary()

    def _rel(self, path: Path):
        try:
            return path.relative_to(self.drive_path)
        except ValueError:
            return path

    def _record(self, original_path, new_path, status: str, message: str = ''):
        self.manifest_rows.append({
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'original_path': str(original_path),
            'new_path': str(new_path),
            'status': status,
            'message': message,
        })

    def write_manifest(self):
        if not self.manifest_file:
            return
        try:
            with open(self.manifest_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=['timestamp', 'original_path', 'new_path', 'status', 'message'],
                )
                writer.writeheader()
                writer.writerows(self.manifest_rows)
            self.log(f"\nSplit manifest saved to: {self.manifest_file}")
        except Exception as exc:
            self.log(f"ERROR: Failed to write manifest: {exc}")

    def print_summary(self):
        self.log(f"\n{'=' * 70}")
        self.log("SUMMARY")
        self.log(f"{'=' * 70}")
        if self.dry_run:
            self.log("\n⚠ DRY RUN - No files were moved")
            self.log(f"  Folders that would be split: {self.stats['would_split']}")
        else:
            self.log(f"  Files moved:        {self.stats['files_moved']}")
            self.log(f"  Subfolders created: {self.stats['groups_created']}")
            if self.stats['errors']:
                self.log(f"  Errors:             {self.stats['errors']}")
        self.log(f"\n{'=' * 70}")
        if self.dry_run:
            self.log("To apply splits, run with --apply flag")
        self.log(f"{'=' * 70}")


# ---------------------------------------------------------------------------
# Logging setup & entry point
# ---------------------------------------------------------------------------

def setup_logging(logs_dir: Optional[str] = None) -> Tuple[str, str]:
    run_dir = resolve_run_output_dir(logs_dir, 'volvo_folder_splitter')
    log_file = run_dir / 'volvo_folder_splitter.log'
    manifest_file = run_dir / 'volvo_split_manifest.csv'
    configure_file_logger('VolvoFolderSplitter', log_file)

    return str(log_file), str(manifest_file)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Split folders exceeding the 254-file Volvo stereo limit.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Finds folders with more than {MAX_FILES_PER_FOLDER} audio files and splits them
into numbered alphabetical subfolders (default max {DEFAULT_GROUP_SIZE} files each).

This tool can be run standalone or through volvo_pipeline.py.
If you apply splits, re-run verification afterwards because the folder
structure has changed.

Examples:
  # Dry run - see what would be split
  python volvo_folder_splitter.py D:/

  # Apply splits
  python volvo_folder_splitter.py D:/ --apply

  # Custom group size
  python volvo_folder_splitter.py D:/ --apply --group-size 150

WARNING: --apply moves files. Always run dry-run first to review the plan!
        """
    )
    parser.add_argument('drive_path', help='Path to USB drive or media folder')
    parser.add_argument('--apply', action='store_true',
                        help='Move files into subfolders (default is dry run)')
    parser.add_argument('--group-size', type=int, default=DEFAULT_GROUP_SIZE,
                        help=f'Max files per subfolder (default: {DEFAULT_GROUP_SIZE})')
    parser.add_argument('--logs-dir', help='Directory to write this run\'s log and manifest artifacts into')
    args = parser.parse_args()

    if not os.path.exists(args.drive_path):
        print(f"ERROR: Path not found: {args.drive_path}")
        sys.exit(1)

    if args.group_size < 1 or args.group_size > MAX_FILES_PER_FOLDER:
        print(f"ERROR: --group-size must be between 1 and {MAX_FILES_PER_FOLDER}")
        sys.exit(1)

    log_file, manifest_file = setup_logging(logs_dir=args.logs_dir)
    print(f"Logging to:      {log_file}")
    print(f"Split manifest:  {manifest_file}\n")

    splitter = VolvoFolderSplitter(
        args.drive_path,
        dry_run=not args.apply,
        group_size=args.group_size,
        manifest_file=manifest_file,
    )
    splitter.split_all()

    print(f"\nLog file saved to: {log_file}")
    print(f"Split manifest:   {manifest_file}")


if __name__ == '__main__':
    main()
