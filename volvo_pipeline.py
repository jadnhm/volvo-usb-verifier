#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Volvo XC70 2012 USB Media Pipeline Coordinator

Runs the recommended workflow:
1. Verify current drive/folder state
2. Run path fixer
3. Re-verify after potential renames
4. Convert lossless files (FLAC, WAV, AIFF, APE, ALAC) to AAC M4A
5. Re-verify after conversions (filenames changed .flac → .m4a)
6. Run ID3 fixer with the fresh verifier CSV
7. Final re-verify

By default all fixer/converter steps run in dry-run mode.
Pass --apply-path, --apply-convert, and/or --apply-id3 to make changes.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Set


def check_ffmpeg():
    """Verify ffmpeg is on PATH before any pipeline steps run."""
    if shutil.which('ffmpeg'):
        return
    print("ERROR: ffmpeg is required by the lossless converter step but was not found on PATH.")
    print()
    print("Install it with:")
    print("  Windows: winget install Gyan.FFmpeg")
    print("  macOS:   brew install ffmpeg")
    print("  Linux:   sudo apt install ffmpeg")
    print()
    print("After installing, restart your terminal so PATH is updated, then re-run this script.")
    sys.exit(1)


def run_step(command, label: str, allowed_exit_codes: Optional[Set[int]] = None):
    """Run a pipeline step and stop on unexpected exit codes."""
    if allowed_exit_codes is None:
        allowed_exit_codes = {0}

    print(f"\n{'=' * 70}")
    print(label)
    print(f"{'=' * 70}")
    result = subprocess.run(command)
    if result.returncode not in allowed_exit_codes:
        print(f"\nERROR: Step failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def newest_matching_file(log_dir: Path, pattern: str, since_mtime: Optional[float] = None) -> Path:
    """Return the newest file matching the pattern, optionally filtered by modified time."""
    candidates = sorted(log_dir.glob(pattern), key=lambda path: path.stat().st_mtime)
    if since_mtime is not None:
        candidates = [path for path in candidates if path.stat().st_mtime >= since_mtime]

    if not candidates:
        raise FileNotFoundError(f"No files found for pattern: {pattern}")

    return candidates[-1]


def run_verifier(python_cmd: str, script_dir: Path, drive_path: str, log_dir: Path, label: str) -> Path:
    """Run verifier and return the newest CSV it produced."""
    before = max((path.stat().st_mtime for path in log_dir.glob('volvo_verify_*.csv')), default=0.0)
    run_step(
        [python_cmd, str(script_dir / 'volvo_usb_verifier.py'), drive_path],
        label,
        allowed_exit_codes={0, 1},
    )
    return newest_matching_file(log_dir, 'volvo_verify_*.csv', since_mtime=before)


def run_path_fixer(python_cmd: str, script_dir: Path, csv_file: Path, drive_path: str,
                   apply_changes: bool, log_dir: Path) -> Path:
    """Run path fixer and return the newest manifest it produced."""
    command = [python_cmd, str(script_dir / 'volvo_path_fixer.py'), str(csv_file), drive_path]
    if apply_changes:
        command.append('--apply')

    before = max((path.stat().st_mtime for path in log_dir.glob('volvo_path_manifest_*.csv')), default=0.0)
    run_step(command, 'Step 2: Run path fixer')
    return newest_matching_file(log_dir, 'volvo_path_manifest_*.csv', since_mtime=before)


def run_converter(python_cmd: str, script_dir: Path, drive_path: str,
                  apply_changes: bool, keep_originals: bool, log_dir: Path) -> Path:
    """Run lossless converter and return the newest manifest it produced."""
    command = [python_cmd, str(script_dir / 'volvo_converter.py'), drive_path]
    if apply_changes:
        command.append('--apply')
    if keep_originals:
        command.append('--keep-originals')

    before = max((path.stat().st_mtime for path in log_dir.glob('volvo_convert_manifest_*.csv')), default=0.0)
    run_step(command, 'Step 4: Convert lossless files to AAC M4A')
    return newest_matching_file(log_dir, 'volvo_convert_manifest_*.csv', since_mtime=before)


def run_id3_fixer(python_cmd: str, script_dir: Path, csv_file: Path, drive_path: str,
                  apply_changes: bool):
    """Run ID3 fixer against a verifier CSV."""
    command = [python_cmd, str(script_dir / 'volvo_usb_fixer.py'), str(csv_file), drive_path]
    if apply_changes:
        command.append('--apply')

    run_step(command, 'Step 6: Run ID3 fixer')


def main():
    parser = argparse.ArgumentParser(
        description='Run the Volvo USB preparation pipeline end-to-end.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run full pipeline
  python volvo_pipeline.py D:/

  # Apply path changes only
  python volvo_pipeline.py D:/ --apply-path

  # Apply path + lossless conversion (keeps originals)
  python volvo_pipeline.py D:/ --apply-path --apply-convert --keep-originals-convert

  # Apply everything
  python volvo_pipeline.py D:/ --apply-path --apply-convert --apply-id3
        """
    )
    parser.add_argument('drive_path', help='Path to USB drive or media folder')
    parser.add_argument('--apply-path', action='store_true', help='Apply path fixes instead of dry-run')
    parser.add_argument('--apply-convert', action='store_true', help='Apply lossless conversions instead of dry-run')
    parser.add_argument('--keep-originals-convert', action='store_true',
                        help='Keep original lossless files after conversion (default: delete on success)')
    parser.add_argument('--apply-id3', action='store_true', help='Apply ID3 fixes instead of dry-run')
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    log_dir = script_dir / 'logs'
    log_dir.mkdir(exist_ok=True)

    python_cmd = sys.executable

    check_ffmpeg()

    initial_csv = run_verifier(python_cmd, script_dir, args.drive_path, log_dir, 'Step 1: Verify drive state')
    print(f"Verifier CSV: {initial_csv}")

    manifest_file = run_path_fixer(
        python_cmd,
        script_dir,
        initial_csv,
        args.drive_path,
        args.apply_path,
        log_dir,
    )
    print(f"Path manifest: {manifest_file}")

    refreshed_csv = run_verifier(python_cmd, script_dir, args.drive_path, log_dir, 'Step 3: Re-verify after path fixer')
    print(f"Post-path-fix verifier CSV: {refreshed_csv}")

    convert_manifest = run_converter(
        python_cmd,
        script_dir,
        args.drive_path,
        args.apply_convert,
        args.keep_originals_convert,
        log_dir,
    )
    print(f"Conversion manifest: {convert_manifest}")

    post_convert_csv = run_verifier(python_cmd, script_dir, args.drive_path, log_dir, 'Step 5: Re-verify after lossless conversion')
    print(f"Post-conversion verifier CSV: {post_convert_csv}")

    run_id3_fixer(python_cmd, script_dir, post_convert_csv, args.drive_path, args.apply_id3)

    final_csv = run_verifier(python_cmd, script_dir, args.drive_path, log_dir, 'Step 7: Final verification')
    print(f"Final verifier CSV: {final_csv}")
    print("\nPipeline complete.")


if __name__ == '__main__':
    main()