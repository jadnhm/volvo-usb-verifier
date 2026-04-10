#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Volvo XC70 2012 USB Media Pipeline Coordinator

Runs the recommended workflow:
0. Optionally clean junk files and split overcrowded folders
1. Verify current drive/folder state
2. Run path fixer
3. Re-verify after potential renames
4. Optionally convert lossless files (FLAC, WAV, AIFF, APE, ALAC) to AAC M4A
5. Re-verify after conversions (filenames changed .flac → .m4a)
6. Run ID3 fixer with the fresh verifier CSV
7. Final re-verify

By default all fixer/converter steps run in dry-run mode.
Pass --apply-path, --apply-convert, and/or --apply-id3 to make changes.
Pass --skip-convert to run the pipeline without requiring ffmpeg.
"""

import argparse
import configparser
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Set

from lib.logging_utils import create_run_output_dir


VERIFIER_EXIT_ISSUES_FOUND = 1
VERIFIER_EXIT_FATAL = 2


def load_config(config_path: Path) -> dict:
    """Load optional pipeline settings from an INI file.

    Returns a dict of dest-name → value suitable for parser.set_defaults().
    CLI flags always take precedence over values here.
    """
    if not config_path.exists():
        return {}

    config = configparser.ConfigParser()
    config.read(str(config_path), encoding='utf-8')

    if 'pipeline' not in config:
        return {}

    section = config['pipeline']
    settings: dict = {}

    bool_keys = [
        'apply_clean', 'run_split', 'apply_split',
        'apply_path', 'skip_convert', 'apply_convert',
        'keep_originals_convert', 'resume_convert', 'apply_id3',
    ]
    for key in bool_keys:
        if key in section:
            try:
                settings[key] = section.getboolean(key)
            except ValueError:
                print(f"WARNING: Invalid boolean value for '{key}' in config file — ignored.")

    if 'split_group_size' in section:
        try:
            settings['split_group_size'] = section.getint('split_group_size')
        except ValueError:
            print("WARNING: Invalid integer value for 'split_group_size' in config file — ignored.")

    return settings


def check_ffmpeg():
    """Verify ffmpeg is on PATH before the converter step runs."""
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


def run_cleaner(python_cmd: str, script_dir: Path, drive_path: str, apply_changes: bool, log_dir: Path):
    """Run junk-file cleaner as an optional pre-step."""
    command = [python_cmd, str(script_dir / 'lib' / 'volvo_usb_cleaner.py'), drive_path, '--logs-dir', str(log_dir)]
    if apply_changes:
        command.append('--apply')
    run_step(command, 'Step 0: Clean junk files')


def run_folder_splitter(python_cmd: str, script_dir: Path, drive_path: str,
                        apply_changes: bool, group_size: int, log_dir: Path) -> Path:
    """Run folder splitter and return the newest manifest it produced."""
    command = [python_cmd, str(script_dir / 'lib' / 'volvo_folder_splitter.py'), drive_path, '--logs-dir', str(log_dir)]
    previous_mtimes = {path: path.stat().st_mtime_ns for path in log_dir.glob('volvo_split_manifest*.csv')}
    if apply_changes:
        command.append('--apply')
    if group_size:
        command.extend(['--group-size', str(group_size)])

    run_step(command, 'Step 0.5: Split overcrowded folders')
    return newest_matching_file(log_dir, 'volvo_split_manifest*.csv', previous_mtimes=previous_mtimes)


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
    return result.returncode


def newest_matching_file(log_dir: Path, pattern: str, since_mtime: Optional[float] = None,
                         previous_mtimes: Optional[Dict[Path, int]] = None) -> Path:
    """Return the newest file matching the pattern, optionally filtered to fresh outputs."""
    candidates = sorted(log_dir.glob(pattern), key=lambda path: path.stat().st_mtime)
    if since_mtime is not None:
        candidates = [path for path in candidates if path.stat().st_mtime >= since_mtime]
    if previous_mtimes is not None:
        candidates = [
            path for path in candidates
            if path not in previous_mtimes or path.stat().st_mtime_ns > previous_mtimes[path]
        ]

    if not candidates:
        raise FileNotFoundError(f"No files found for pattern: {pattern}")

    return candidates[-1]


def run_verifier(python_cmd: str, script_dir: Path, drive_path: str, log_dir: Path, label: str) -> Path:
    """Run verifier and return the newest CSV it produced."""
    previous_mtimes = {path: path.stat().st_mtime_ns for path in log_dir.glob('volvo_verify_*.csv')}
    run_step(
        [python_cmd, str(script_dir / 'lib' / 'volvo_usb_verifier.py'), drive_path, '--logs-dir', str(log_dir)],
        label,
        allowed_exit_codes={0, VERIFIER_EXIT_ISSUES_FOUND},
    )
    try:
        return newest_matching_file(log_dir, 'volvo_verify_*.csv', previous_mtimes=previous_mtimes)
    except FileNotFoundError:
        print("\nERROR: Verifier did not produce a fresh CSV report. Refusing to continue with a stale report.")
        sys.exit(VERIFIER_EXIT_FATAL)


def run_path_fixer(python_cmd: str, script_dir: Path, csv_file: Path, drive_path: str,
                   apply_changes: bool, log_dir: Path) -> Path:
    """Run path fixer and return the newest manifest it produced."""
    command = [python_cmd, str(script_dir / 'lib' / 'volvo_path_fixer.py'), str(csv_file), drive_path, '--logs-dir', str(log_dir)]
    previous_mtimes = {path: path.stat().st_mtime_ns for path in log_dir.glob('volvo_path_manifest*.csv')}
    if apply_changes:
        command.append('--apply')

    run_step(command, 'Step 2: Run path fixer')
    return newest_matching_file(log_dir, 'volvo_path_manifest*.csv', previous_mtimes=previous_mtimes)


def run_converter(python_cmd: str, script_dir: Path, drive_path: str,
                  apply_changes: bool, keep_originals: bool, resume: bool,
                  log_dir: Path) -> Path:
    """Run lossless converter and return the newest manifest it produced."""
    command = [python_cmd, str(script_dir / 'lib' / 'volvo_converter.py'), drive_path, '--logs-dir', str(log_dir)]
    previous_mtimes = {path: path.stat().st_mtime_ns for path in log_dir.glob('volvo_convert_manifest*.csv')}
    if apply_changes:
        command.append('--apply')
    if keep_originals:
        command.append('--keep-originals')
    if resume:
        command.append('--resume')

    run_step(command, 'Step 4: Convert lossless files to AAC M4A')
    return newest_matching_file(log_dir, 'volvo_convert_manifest*.csv', previous_mtimes=previous_mtimes)


def run_id3_fixer(python_cmd: str, script_dir: Path, csv_file: Path, drive_path: str,
                  apply_changes: bool, log_dir: Path):
    """Run ID3 fixer against a verifier CSV."""
    command = [python_cmd, str(script_dir / 'lib' / 'volvo_usb_fixer.py'), str(csv_file), drive_path, '--logs-dir', str(log_dir)]
    if apply_changes:
        command.append('--apply')

    run_step(command, 'Step 6: Run ID3 fixer')


def create_step_output_dir(run_dir: Path, step_name: str) -> Path:
    """Create a timestamped per-step artifact directory inside a pipeline run."""
    return create_run_output_dir(run_dir, step_name)


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

  # Run the pipeline without conversion or ffmpeg
  python volvo_pipeline.py D:/ --skip-convert

  # Resume an interrupted conversion job within the pipeline
  python volvo_pipeline.py D:/ --apply-convert --resume-convert

  # Preview folder splitting before the main verify step
  python volvo_pipeline.py D:/ --run-split

  # Apply everything
  python volvo_pipeline.py D:/ --apply-path --apply-convert --apply-id3
        """
    )
    parser.add_argument('drive_path', help='Path to USB drive or media folder')
    parser.add_argument('--apply-clean', action='store_true', help='Delete junk/metadata files instead of dry-run')
    parser.add_argument('--run-split', action='store_true',
                        help='Include the folder splitter step before verification (dry run unless --apply-split is also set)')
    parser.add_argument('--apply-split', action='store_true',
                        help='Move files into subfolders during the folder splitter step')
    parser.add_argument('--split-group-size', type=int, default=200,
                        help='Max files per split subfolder when using the folder splitter (default: 200)')
    parser.add_argument('--apply-path', action='store_true', help='Apply path fixes instead of dry-run')
    parser.add_argument('--skip-convert', action='store_true',
                        help='Skip the lossless converter step entirely (no ffmpeg required)')
    parser.add_argument('--apply-convert', action='store_true', help='Apply lossless conversions instead of dry-run')
    parser.add_argument('--keep-originals-convert', action='store_true',
                        help='Keep original lossless files after conversion (default: delete on success)')
    parser.add_argument('--resume-convert', action='store_true',
                        help='Pass --resume to the converter so existing .m4a outputs are skipped')
    parser.add_argument('--apply-id3', action='store_true', help='Apply ID3 fixes instead of dry-run')
    parser.add_argument('--config', metavar='FILE',
                        help='Path to an INI config file (default: volvo_pipeline.ini in the same folder)')

    # Pre-parse to find --config before setting defaults, then re-parse.
    pre, _ = parser.parse_known_args()
    config_path = Path(pre.config) if pre.config else Path(__file__).resolve().parent / 'volvo_pipeline.ini'
    config_defaults = load_config(config_path)
    if config_defaults:
        print(f"Loaded config from: {config_path}")
        parser.set_defaults(**config_defaults)

    args = parser.parse_args()

    if args.resume_convert and args.skip_convert:
        parser.error('--resume-convert cannot be used with --skip-convert')

    script_dir = Path(__file__).resolve().parent
    log_root = script_dir / 'logs'
    log_root.mkdir(exist_ok=True)
    pipeline_run_dir = create_run_output_dir(log_root, 'volvo_pipeline')
    print(f"Pipeline artifacts: {pipeline_run_dir}")

    python_cmd = sys.executable

    run_cleaner(
        python_cmd,
        script_dir,
        args.drive_path,
        args.apply_clean,
        create_step_output_dir(pipeline_run_dir, '00_cleaner'),
    )

    if args.run_split or args.apply_split:
        split_manifest = run_folder_splitter(
            python_cmd,
            script_dir,
            args.drive_path,
            args.apply_split,
            args.split_group_size,
            create_step_output_dir(pipeline_run_dir, '00_folder_splitter'),
        )
        print(f"Split manifest: {split_manifest}")

    initial_csv = run_verifier(
        python_cmd,
        script_dir,
        args.drive_path,
        create_step_output_dir(pipeline_run_dir, '01_verify_initial'),
        'Step 1: Verify drive state',
    )
    print(f"Verifier CSV: {initial_csv}")

    manifest_file = run_path_fixer(
        python_cmd,
        script_dir,
        initial_csv,
        args.drive_path,
        args.apply_path,
        create_step_output_dir(pipeline_run_dir, '02_path_fixer'),
    )
    print(f"Path manifest: {manifest_file}")

    refreshed_csv = run_verifier(
        python_cmd,
        script_dir,
        args.drive_path,
        create_step_output_dir(pipeline_run_dir, '03_verify_post_path'),
        'Step 3: Re-verify after path fixer',
    )
    print(f"Post-path-fix verifier CSV: {refreshed_csv}")

    id3_input_csv = refreshed_csv
    if not args.skip_convert:
        if args.apply_convert:
            check_ffmpeg()
        convert_manifest = run_converter(
            python_cmd,
            script_dir,
            args.drive_path,
            args.apply_convert,
            args.keep_originals_convert,
            args.resume_convert,
            create_step_output_dir(pipeline_run_dir, '04_converter'),
        )
        print(f"Conversion manifest: {convert_manifest}")

        post_convert_csv = run_verifier(
            python_cmd,
            script_dir,
            args.drive_path,
            create_step_output_dir(pipeline_run_dir, '05_verify_post_convert'),
            'Step 5: Re-verify after lossless conversion',
        )
        print(f"Post-conversion verifier CSV: {post_convert_csv}")
        id3_input_csv = post_convert_csv
    else:
        print("Conversion step skipped (--skip-convert).")

    run_id3_fixer(
        python_cmd,
        script_dir,
        id3_input_csv,
        args.drive_path,
        args.apply_id3,
        create_step_output_dir(pipeline_run_dir, '06_id3_fixer'),
    )

    final_csv = run_verifier(
        python_cmd,
        script_dir,
        args.drive_path,
        create_step_output_dir(pipeline_run_dir, '07_verify_final'),
        'Step 7: Final verification',
    )
    print(f"Final verifier CSV: {final_csv}")
    print("\nPipeline complete.")


if __name__ == '__main__':
    main()