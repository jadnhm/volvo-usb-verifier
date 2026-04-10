#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Volvo XC70 2012 USB Lossless Audio Converter

Converts lossless and uncompressed audio files to AAC 192kbps M4A,
which is natively supported by the Volvo XC70 stereo.

Converts:
  - FLAC  (.flac)
  - WAV   (.wav)
  - AIFF  (.aiff, .aif)
  - APE   (.ape)
  - ALAC  (.alac, or .m4a/.m4b files using the ALAC codec)

Skips everything else — MP3, WMA, and already-compliant AAC are left untouched.
VBR / bitrate / sample-rate issues in MP3 files are NOT converted; keep them as
warnings and handle with foobar2000 or similar if needed.

Requires ffmpeg on PATH for live conversions:
  Windows: winget install Gyan.FFmpeg
  macOS:   brew install ffmpeg
  Linux:   sudo apt install ffmpeg

Output: AAC 192kbps, 44.1 kHz, inside .m4a container, metadata preserved.

Writes logs/volvo_convert_manifest_YYYYMMDD_HHMMSS.csv recording every
file processed (whether converted, skipped, or failed).

WARNING: With --apply the original lossless file is deleted after a successful
         conversion. Use --keep-originals to preserve source files.
"""

import os
import sys
import csv
import logging
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from logging_utils import configure_file_logger, resolve_run_output_dir
except ImportError:
    from lib.logging_utils import configure_file_logger, resolve_run_output_dir
from collections import defaultdict

# Fix Windows console encoding
if sys.platform == "win32":
    import io
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    from mutagen.mp4 import MP4
    _MUTAGEN_AVAILABLE = True
except ImportError:
    _MUTAGEN_AVAILABLE = False

# ---------------------------------------------------------------------------
# Lossless format definitions
# ---------------------------------------------------------------------------

# Extensions that are always lossless / uncompressed
LOSSLESS_EXTENSIONS = {'.flac', '.wav', '.aiff', '.aif', '.ape', '.alac'}

# Extensions that might be lossless (ALAC) or lossy (AAC) — must inspect codec
MAYBE_LOSSLESS_EXTENSIONS = {'.m4a', '.m4b'}

TARGET_CODEC = 'aac'
TARGET_BITRATE = '192k'
TARGET_SAMPLE_RATE = '44100'
TARGET_EXTENSION = '.m4a'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check_ffmpeg() -> str:
    """Return path to ffmpeg, or exit with a helpful message if not found."""
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        print("ERROR: ffmpeg not found on PATH.")
        print()
        print("Install it with:")
        print("  Windows: winget install Gyan.FFmpeg")
        print("  macOS:   brew install ffmpeg")
        print("  Linux:   sudo apt install ffmpeg")
        print()
        print("After installing, restart your terminal so PATH is updated, then re-run this script.")
        sys.exit(1)
    return ffmpeg_path


def is_alac(file_path: Path) -> bool:
    """Return True if an .m4a/.m4b file uses the ALAC (lossless) codec."""
    if not _MUTAGEN_AVAILABLE:
        return False
    try:
        audio = MP4(file_path)
        if audio.info and hasattr(audio.info, 'codec'):
            return str(audio.info.codec).lower().startswith('alac')
    except Exception:
        pass
    return False


def find_lossless_files(drive_path: Path) -> List[Path]:
    """Walk drive_path and return all lossless / uncompressed audio files."""
    results = []
    for root, _dirs, files in os.walk(drive_path):
        for filename in files:
            file_path = Path(root) / filename
            ext = file_path.suffix.lower()
            if ext in LOSSLESS_EXTENSIONS:
                results.append(file_path)
            elif ext in MAYBE_LOSSLESS_EXTENSIONS and is_alac(file_path):
                results.append(file_path)
    return results


def safe_output_path(input_path: Path) -> Path:
    """Return a .m4a output path that does not collide with an existing file."""
    candidate = input_path.with_suffix(TARGET_EXTENSION)
    if not candidate.exists() or candidate == input_path:
        return candidate
    # Avoid clobbering an existing (different) .m4a
    return input_path.with_stem(input_path.stem + '_converted').with_suffix(TARGET_EXTENSION)


def run_ffmpeg(ffmpeg_path: str, input_path: Path, output_path: Path, timeout: int = 300) -> Tuple[bool, str]:
    """Run ffmpeg to convert input_path → output_path. Returns (success, message)."""
    cmd = [
        ffmpeg_path,
        '-i', str(input_path),
        '-c:a', TARGET_CODEC,
        '-b:a', TARGET_BITRATE,
        '-ar', TARGET_SAMPLE_RATE,
        '-map_metadata', '0',   # preserve all metadata
        '-movflags', '+faststart',
        '-y',                   # overwrite output if it exists
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return True, f"Converted → {output_path.name}"
        stderr_tail = result.stderr[-400:].strip() if result.stderr else 'no stderr'
        return False, f"ffmpeg exited {result.returncode}: {stderr_tail}"
    except subprocess.TimeoutExpired:
        return False, f"ffmpeg timed out (>{timeout}s)"
    except Exception as exc:
        return False, f"Unexpected error: {exc}"


def validate_converted_output(output_path: Path) -> Tuple[bool, str]:
    """Verify a converted output exists and looks usable before deleting source."""
    if not output_path.exists():
        return False, "conversion reported success but output file was not created"

    try:
        size = output_path.stat().st_size
    except OSError as exc:
        return False, f"could not stat output file: {exc}"

    if size <= 0:
        return False, "conversion produced a zero-byte output file"

    if _MUTAGEN_AVAILABLE:
        try:
            audio = MP4(output_path)
            if not getattr(audio, 'info', None):
                return False, "converted file could not be parsed as an MP4/AAC file"
        except Exception as exc:
            return False, f"converted file could not be parsed as an MP4/AAC file: {exc}"

    return True, "output file verified"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class VolvoConverter:
    """Converts lossless audio to AAC M4A for Volvo XC70 compatibility."""

    def __init__(self, drive_path: str, dry_run: bool = True,
                 keep_originals: bool = False,
                 resume: bool = False,
                 manifest_file: Optional[str] = None):
        self.drive_path = Path(drive_path)
        self.dry_run = dry_run
        self.keep_originals = keep_originals
        self.resume = resume
        self.manifest_file = Path(manifest_file) if manifest_file else None
        self.logger = logging.getLogger('VolvoConverter')
        self.stats: Dict[str, int] = defaultdict(int)
        self.manifest_rows: List[Dict] = []

    def log(self, message: str):
        print(message)
        self.logger.info(message)

    def convert_all(self, ffmpeg_path: str):
        mode = "DRY RUN" if self.dry_run else "LIVE MODE"
        self.log(f"\n{'=' * 70}")
        self.log(f"Volvo Lossless Converter - {mode}")
        self.log(f"{'=' * 70}")

        if self.dry_run:
            self.log("\n⚠ DRY RUN: No files will be modified. Use --apply to make changes.")
        else:
            orig_fate = "kept (--keep-originals)" if self.keep_originals else "deleted after successful conversion"
            self.log(f"\n⚠ LIVE MODE: Originals will be {orig_fate}!")

        self.log(f"\nScanning for lossless files in: {self.drive_path}")
        lossless_files = find_lossless_files(self.drive_path)

        if not lossless_files:
            self.log("No lossless/uncompressed files found. Nothing to do.")
            self.write_manifest()
            return

        # Show breakdown by extension
        ext_counts: Dict[str, int] = defaultdict(int)
        for f in lossless_files:
            ext_counts[f.suffix.lower()] += 1
        self.log(f"\nFound {len(lossless_files)} lossless files:")
        for ext, count in sorted(ext_counts.items()):
            self.log(f"  {ext.upper()}: {count}")

        self.log(f"\nTarget: AAC {TARGET_BITRATE}, {TARGET_SAMPLE_RATE} Hz, .m4a container")

        if self.resume:
            self.log("\nResume mode: files with an existing .m4a output will be skipped.")

        self.log(f"Processing {len(lossless_files)} files...\n")

        total = len(lossless_files)
        for idx, input_path in enumerate(lossless_files, 1):
            rel_input = input_path.relative_to(self.drive_path)
            preferred_output = input_path.with_suffix(TARGET_EXTENSION)
            output_path = safe_output_path(input_path)
            rel_output = output_path.relative_to(self.drive_path)

            # Resume: skip if output already exists (from a previous interrupted run)
            if self.resume and preferred_output.exists() and preferred_output != input_path:
                self.log(f"  [{idx}/{total}] Skipping (already converted): {rel_input}")
                self.stats['skipped_resume'] += 1
                self._record(str(rel_input), str(preferred_output.relative_to(self.drive_path)), 'skipped_already_converted',
                             'Output .m4a already exists')
                continue

            if self.dry_run:
                self.log(f"✓ [{idx}/{total}] Would convert: {rel_input}")
                self.log(f"    → {rel_output.name} (AAC {TARGET_BITRATE})")
                self.stats['would_convert'] += 1
                self._record(str(rel_input), str(rel_output), 'would_convert',
                             f"Would convert to AAC {TARGET_BITRATE}")
                continue

            # — Live mode —
            success, message = run_ffmpeg(ffmpeg_path, input_path, output_path)

            if success:
                output_ok, output_message = validate_converted_output(output_path)
                if not output_ok:
                    success = False
                    message = f"{message} but {output_message}"

            if success:
                self.stats['converted'] += 1
                status = 'converted'
                if not self.keep_originals:
                    try:
                        input_path.unlink()
                        status = 'converted_original_deleted'
                    except Exception as exc:
                        message += f" (warning: could not delete original: {exc})"
                        status = 'converted_original_kept_on_error'
                self.log(f"✓ [{idx}/{total}] {rel_input}")
                self.log(f"    - {message}")
            else:
                self.stats['failed'] += 1
                status = 'failed'
                self.log(f"✗ [{idx}/{total}] {rel_input}")
                self.log(f"    - {message}")
                # Clean up partial output if it exists
                if output_path.exists() and output_path != input_path:
                    try:
                        output_path.unlink()
                    except Exception:
                        pass

            self._record(str(rel_input), str(rel_output) if success else '', status, message)

        self.write_manifest()
        self.print_summary()

    def _record(self, original_path: str, new_path: str, status: str, message: str):
        self.manifest_rows.append({
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'original_path': original_path,
            'new_path': new_path,
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
            self.log(f"Conversion manifest saved to: {self.manifest_file}")
        except Exception as exc:
            self.log(f"ERROR: Failed to write manifest: {exc}")

    def print_summary(self):
        self.log(f"\n{'=' * 70}")
        self.log("SUMMARY")
        self.log(f"{'=' * 70}")

        if self.dry_run:
            self.log("\n⚠ DRY RUN - No files were modified")
            self.log(f"  Files that would be converted: {self.stats['would_convert']}")
        else:
            self.log(f"  Files converted: {self.stats['converted']}")
            if self.stats.get('skipped_resume'):
                self.log(f"  Files skipped (resume): {self.stats['skipped_resume']}")
            if self.stats['failed']:
                self.log(f"  Files failed:    {self.stats['failed']}")

        if self.manifest_file:
            self.log(f"  Manifest: {self.manifest_file}")

        self.log(f"\n{'=' * 70}")
        if self.dry_run:
            self.log("To apply conversions, run with --apply flag")
        self.log(f"{'=' * 70}")


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(logs_dir: Optional[str] = None) -> Tuple[str, str]:
    run_dir = resolve_run_output_dir(logs_dir, 'volvo_converter')
    log_file = run_dir / 'volvo_converter.log'
    manifest_file = run_dir / 'volvo_convert_manifest.csv'
    configure_file_logger('VolvoConverter', log_file)

    return str(log_file), str(manifest_file)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Convert lossless audio to AAC M4A for Volvo XC70 compatibility.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Converts lossless formats (FLAC, WAV, AIFF, APE, ALAC) to AAC 192kbps M4A.
Leaves MP3, WMA, and existing AAC/M4A files untouched.
VBR/bitrate/sample-rate issues in MP3 files are left as warnings.

Live conversions require ffmpeg: https://ffmpeg.org/download.html

Examples:
  # Dry run - see what would be converted
  python volvo_converter.py D:/

  # Convert and delete originals after success
  python volvo_converter.py D:/ --apply

  # Convert but keep original lossless files
  python volvo_converter.py D:/ --apply --keep-originals

WARNING: Always backup your files before running with --apply!
        """
    )
    parser.add_argument('drive_path', help='Path to USB drive or media folder')
    parser.add_argument('--apply', action='store_true',
                        help='Apply conversions (default is dry run)')
    parser.add_argument('--keep-originals', action='store_true',
                        help='Keep original files after successful conversion '
                             '(default: delete originals)')
    parser.add_argument('--resume', action='store_true',
                        help='Skip files whose .m4a output already exists '
                             '(useful after an interrupted run)')
    parser.add_argument('--logs-dir', help='Directory to write this run\'s log and manifest artifacts into')
    args = parser.parse_args()

    if not os.path.exists(args.drive_path):
        print(f"ERROR: Path not found: {args.drive_path}")
        sys.exit(1)

    log_file, manifest_file = setup_logging(logs_dir=args.logs_dir)
    print(f"Logging to: {log_file}")
    print(f"Conversion manifest will be saved to: {manifest_file}\n")

    dry_run = not args.apply
    ffmpeg_path = 'ffmpeg'
    if args.apply:
        ffmpeg_path = check_ffmpeg()
        print(f"Using ffmpeg: {ffmpeg_path}\n")

    converter = VolvoConverter(
        args.drive_path,
        dry_run=dry_run,
        keep_originals=args.keep_originals,
        resume=args.resume,
        manifest_file=manifest_file,
    )
    converter.convert_all(ffmpeg_path)

    print(f"\nLog file saved to: {log_file}")
    print(f"Conversion manifest saved to: {manifest_file}")


if __name__ == '__main__':
    main()
