#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Volvo XC70 2012 USB Junk File Cleaner

Removes system/metadata files and directories that don't belong on a media
USB drive and can confuse some car stereos or waste space.

Files/directories targeted:
  .DS_Store, ._*         macOS metadata and resource forks
  __MACOSX/              macOS zip artifact directories
  Thumbs.db              Windows thumbnail cache
  desktop.ini            Windows folder customization
  autorun.inf            Windows autorun (not needed on media drives)
  .Spotlight-V100/       macOS Spotlight search index
  .fseventsd/            macOS file system events daemon
  .Trashes/              macOS Trash folder
  .TemporaryItems/       macOS temporary files
  .recycler/             Legacy Windows Recycle Bin
  $RECYCLE.BIN/          Windows Recycle Bin
  System Volume Information/  Windows system folder
  FOUND.000/ etc.        Windows CHKDSK recovered-file folders

Dry-run by default. Pass --apply to delete.

Writes logs/volvo_cleaner_YYYYMMDD_HHMMSS.log.
"""

import os
import sys
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

# Fix Windows console encoding
if sys.platform == "win32":
    import io
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Junk definitions
# ---------------------------------------------------------------------------

# Exact (lower-cased) filenames to remove
JUNK_FILENAMES = {
    '.ds_store',
    '._.ds_store',
    'thumbs.db',
    'desktop.ini',
    'autorun.inf',
}

# Filename prefix indicating a macOS resource fork written to FAT32
RESOURCE_FORK_PREFIX = '._'

# Directory names (lower-cased) to remove entirely (including all contents)
JUNK_DIR_NAMES = {
    '__macosx',
    '.spotlight-v100',
    '.fseventsd',
    '.trashes',
    '.temporaryitems',
    '.recycler',
    '$recycle.bin',
    'system volume information',
}

# Directory name prefixes written by Windows CHKDSK recovered-file folders
CHKDSK_DIR_PREFIXES = ('found.',)


class VolvoUSBCleaner:
    """Finds and removes junk files/directories from a media USB drive."""

    def __init__(self, drive_path: str, dry_run: bool = True):
        self.drive_path = Path(drive_path)
        self.dry_run = dry_run
        self.logger = logging.getLogger('VolvoUSBCleaner')
        self.junk_files: List[Tuple[Path, str]] = []   # (path, reason)
        self.junk_dirs: List[Tuple[Path, str]] = []    # (path, reason)
        self.total_size_bytes = 0
        self.errors: List[str] = []

    def log(self, message: str):
        print(message)
        self.logger.info(message)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self):
        """Walk the drive and collect all junk files and directories."""
        self.log(f"\nScanning: {self.drive_path}")
        for root, dirs, files in os.walk(self.drive_path, topdown=True):
            root_path = Path(root)

            # Inspect directories; don't descend into junk dirs
            for d in list(dirs):
                d_lower = d.lower()
                reason = None
                if d_lower in JUNK_DIR_NAMES:
                    reason = 'system/metadata directory'
                elif any(d_lower.startswith(p) for p in CHKDSK_DIR_PREFIXES):
                    reason = 'CHKDSK recovered-files directory'

                if reason:
                    dir_path = root_path / d
                    self.junk_dirs.append((dir_path, reason))
                    self.total_size_bytes += self._dir_size(dir_path)
                    dirs.remove(d)  # prevent os.walk descending into it

            # Inspect files
            for f in files:
                f_lower = f.lower()
                reason = None
                if f_lower in JUNK_FILENAMES:
                    reason = 'system/metadata file'
                elif f.startswith(RESOURCE_FORK_PREFIX) and len(f) > len(RESOURCE_FORK_PREFIX):
                    reason = 'macOS resource fork'

                if reason:
                    file_path = root_path / f
                    try:
                        self.total_size_bytes += file_path.stat().st_size
                    except OSError:
                        pass
                    self.junk_files.append((file_path, reason))

    @staticmethod
    def _dir_size(path: Path) -> int:
        total = 0
        try:
            for dp, _, fns in os.walk(path):
                for fn in fns:
                    try:
                        total += (Path(dp) / fn).stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def clean_all(self):
        mode = "DRY RUN" if self.dry_run else "LIVE MODE"
        self.log(f"\n{'=' * 70}")
        self.log(f"Volvo USB Cleaner - {mode}")
        self.log(f"{'=' * 70}")

        if self.dry_run:
            self.log("\n⚠ DRY RUN: No files will be deleted. Use --apply to delete.")
        else:
            self.log("\n⚠ LIVE MODE: Files will be permanently deleted!")

        self.scan()

        total_items = len(self.junk_files) + len(self.junk_dirs)
        if total_items == 0:
            self.log("\n✓ No junk files found. Drive is clean.")
            return

        size_str = self._format_size(self.total_size_bytes)
        self.log(
            f"\nFound {len(self.junk_dirs)} junk directories and "
            f"{len(self.junk_files)} junk files ({size_str})"
        )

        verb = "Would remove" if self.dry_run else "Removing"
        for dir_path, reason in self.junk_dirs:
            self.log(f"  {verb} dir:  {self._rel(dir_path)}  [{reason}]")
        for file_path, reason in self.junk_files:
            self.log(f"  {verb} file: {self._rel(file_path)}  [{reason}]")

        if not self.dry_run:
            removed_dirs = removed_files = 0
            for dir_path, _ in self.junk_dirs:
                try:
                    shutil.rmtree(dir_path)
                    removed_dirs += 1
                except Exception as exc:
                    self.errors.append(f"Dir {self._rel(dir_path)}: {exc}")
            for file_path, _ in self.junk_files:
                try:
                    file_path.unlink()
                    removed_files += 1
                except Exception as exc:
                    self.errors.append(f"File {self._rel(file_path)}: {exc}")

            self.log(
                f"\n✓ Removed {removed_dirs} directories and "
                f"{removed_files} files ({size_str} freed)"
            )
            if self.errors:
                self.log(f"\n⚠ {len(self.errors)} error(s):")
                for err in self.errors:
                    self.log(f"  {err}")

        self.log(f"\n{'=' * 70}")
        if self.dry_run:
            self.log("To delete these items, run with --apply flag")
        self.log(f"{'=' * 70}")

    def _rel(self, path: Path) -> Path:
        try:
            return path.relative_to(self.drive_path)
        except ValueError:
            return path

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        kb = size_bytes / 1024
        if kb < 1024:
            return f"{kb:.1f} KB"
        return f"{kb / 1024:.1f} MB"


# ---------------------------------------------------------------------------
# Logging setup & entry point
# ---------------------------------------------------------------------------

def setup_logging() -> str:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"volvo_cleaner_{timestamp}.log"

    logger = logging.getLogger('VolvoUSBCleaner')
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(fh)

    return str(log_file)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Remove junk metadata/system files from a Volvo USB drive.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Removes macOS and Windows system/metadata files that waste space and can
confuse car stereos:
  .DS_Store, ._* (macOS resource forks), __MACOSX/ (zip artifacts),
  Thumbs.db, desktop.ini (Windows), System Volume Information/,
  .Spotlight-V100/, FOUND.000/ (CHKDSK), etc.

Examples:
  # Dry run - see what would be removed
  python volvo_usb_cleaner.py D:/

  # Delete junk files
  python volvo_usb_cleaner.py D:/ --apply

WARNING: --apply permanently deletes files. Review dry-run output first!
        """
    )
    parser.add_argument('drive_path', help='Path to USB drive or media folder')
    parser.add_argument('--apply', action='store_true',
                        help='Delete junk files (default is dry run)')
    args = parser.parse_args()

    if not os.path.exists(args.drive_path):
        print(f"ERROR: Path not found: {args.drive_path}")
        sys.exit(1)

    log_file = setup_logging()
    print(f"Logging to: {log_file}\n")

    cleaner = VolvoUSBCleaner(args.drive_path, dry_run=not args.apply)
    cleaner.clean_all()

    print(f"\nLog file saved to: {log_file}")


if __name__ == '__main__':
    main()
