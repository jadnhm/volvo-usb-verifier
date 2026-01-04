#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Volvo XC70 2012 USB Filename Fixer

This script processes the CSV output from volvo_usb_verifier.py and automatically
fixes filename issues to make files compatible with the 2012 Volvo XC70 stereo.

Fixes applied:
- Shorten filenames that exceed 64 characters
- Replace extended ASCII characters with safe alternatives

Note: Path length issues must be handled manually or with a separate tool.

WARNING: This script renames files. Always backup your files first!
"""

import os
import sys
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict
import re

# Fix Windows console encoding issues
if sys.platform == "win32":
    import io
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


class VolvoPathFixer:
    """Fixes filename and character issues based on CSV report from volvo_usb_verifier.py"""

    # Character replacements for extended ASCII
    CHAR_REPLACEMENTS = {
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'á': 'a', 'à': 'a', 'â': 'a', 'ä': 'a', 'ã': 'a', 'å': 'a', 'æ': 'ae',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'ô': 'o', 'ö': 'o', 'õ': 'o', 'ø': 'o', 'œ': 'oe',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ñ': 'n', 'ç': 'c',
        '¿': '', '¡': '', '«': '"', '»': '"',
        '°': '', '±': '+', '²': '2', '³': '3',
        'µ': 'u', '¶': '', '·': '', '¸': '',
        '¹': '1', 'º': 'o', '¼': '1-4', '½': '1-2', '¾': '3-4',
        '×': 'x', '÷': '/',
        'ÿ': 'y'
    }

    # Common abbreviations for shortening
    WORD_REPLACEMENTS = {
        'The ': '',
        ' and ': ' & ',
        ' And ': ' & ',
        'featuring': 'ft',
        'Featuring': 'ft',
        'Live': 'Lv',
        'Version': 'Ver',
        'Original': 'Orig',
        'Remastered': 'Rmstr',
        'Deluxe': 'Dlx',
        'Edition': 'Ed',
        'Collection': 'Coll',
        'Greatest': 'Grt',
        'Compilation': 'Comp',
        'Anniversary': 'Anniv',
        'Previously': 'Prev',
        'Unreleased': 'Unrel',
    }

    MAX_PATH_LENGTH = 60
    MAX_FILENAME_LENGTH = 64

    def __init__(self, csv_file: str, drive_path: str, dry_run: bool = True):
        self.csv_file = Path(csv_file)
        self.drive_path = Path(drive_path)
        self.dry_run = dry_run
        self.logger = logging.getLogger('VolvoPathFixer')

        # Statistics
        self.stats = defaultdict(int)
        self.fixed_files = []
        self.failed_files = []
        self.renamed_dirs = {}  # Track directory renames {old_path: new_path}
        self.paths_too_long = []  # Paths that exceed 60 chars (for reporting only)

    def log(self, message: str):
        """Log message to both console and file."""
        print(message)
        self.logger.info(message)

    def load_issues(self) -> Dict[str, List[Dict]]:
        """Load issues from CSV file, grouped by file path."""
        issues_by_file = defaultdict(list)

        try:
            with open(self.csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Process filename, character, and path length issues
                    # (we fix filename/chars but only report path length)
                    if row['issue_type'] in ('Filename Length', 'Invalid Characters', 'Path Length'):
                        file_path = row['file_path']
                        issues_by_file[file_path].append(row)

            self.log(f"Loaded issues for {len(issues_by_file)} files from {self.csv_file}")
            return issues_by_file
        except Exception as e:
            self.log(f"ERROR: Failed to load CSV file: {e}")
            sys.exit(1)

    def fix_all(self):
        """Process all files and apply filename/character fixes."""
        mode = "DRY RUN" if self.dry_run else "LIVE MODE"
        self.log(f"\n{'='*70}")
        self.log(f"Volvo Filename Fixer - {mode}")
        self.log(f"{'='*70}")

        if self.dry_run:
            self.log("\n⚠ DRY RUN: No files will be modified. Use --apply to make changes.")
        else:
            self.log("\n⚠ LIVE MODE: Files and folders will be renamed!")

        # Load issues
        issues_by_file = self.load_issues()

        # Group by issue type for statistics
        issue_types = defaultdict(int)
        for issues in issues_by_file.values():
            for issue in issues:
                issue_types[issue['issue_type']] += 1

        self.log(f"\nIssue breakdown:")
        for issue_type, count in sorted(issue_types.items(), key=lambda x: -x[1]):
            self.log(f"  {issue_type}: {count}")

        # Process files
        total_files = len(issues_by_file)
        self.log(f"\nProcessing {total_files} files...")

        for idx, (file_path, issues) in enumerate(issues_by_file.items(), 1):
            if idx % 100 == 0:
                self.log(f"  Processed {idx}/{total_files} files...")

            self._process_file(file_path, issues)

        # Print summary
        self.print_summary()

    def _process_file(self, file_path: str, issues: List[Dict]):
        """Process a single file - fix what we can, report what we can't."""
        full_path = self.drive_path / file_path

        if not full_path.exists():
            self.failed_files.append((file_path, "File not found"))
            return

        # Determine what issues exist
        has_long_path = any(i['issue_type'] == 'Path Length' for i in issues)
        has_long_filename = any(i['issue_type'] == 'Filename Length' for i in issues)
        has_invalid_chars = any(i['issue_type'] == 'Invalid Characters' for i in issues)

        fixes_applied = []
        new_path = Path(file_path)

        # Fix invalid characters first
        if has_invalid_chars:
            new_path = Path(self._fix_invalid_chars(str(new_path)))
            fixes_applied.append("Replaced invalid characters")
            self.stats['invalid_chars_fixed'] += 1

        # Fix long filename
        if has_long_filename:
            new_filename = self._shorten_filename(new_path.name)
            new_path = new_path.parent / new_filename
            fixes_applied.append(f"Shortened filename to {len(new_filename)} chars")
            self.stats['filenames_shortened'] += 1

        # Check if path is too long (for reporting only, don't try to fix)
        if len(str(new_path)) > self.MAX_PATH_LENGTH:
            self.paths_too_long.append((file_path, str(new_path), len(str(new_path))))
            fixes_applied.append(f"⚠ WARNING: Path is {len(str(new_path))} chars (exceeds 60 limit)")

        # Report on this file if there are any issues
        if fixes_applied:
            # Something to report (fixes or warnings)
            if str(new_path) != file_path:
                # File will be renamed
                if self.dry_run:
                    self.log(f"Would rename:")
                    self.log(f"  FROM: {file_path}")
                    self.log(f"  TO:   {new_path}")
                    for fix in fixes_applied:
                        self.log(f"    - {fix}")
                    self.fixed_files.append((file_path, str(new_path)))
                else:
                    # Perform actual rename
                    try:
                        new_full_path = self.drive_path / new_path
                        new_full_path.parent.mkdir(parents=True, exist_ok=True)
                        full_path.rename(new_full_path)
                        self.log(f"✓ Renamed: {file_path} -> {new_path}")
                        for fix in fixes_applied:
                            self.log(f"    - {fix}")
                        self.fixed_files.append((file_path, str(new_path)))
                        self.stats['files_renamed'] += 1
                    except Exception as e:
                        self.log(f"✗ Failed to rename {file_path}: {e}")
                        self.failed_files.append((file_path, str(e)))
            else:
                # File has issues but won't be renamed (path too long only)
                if self.dry_run:
                    self.log(f"File with issues (cannot fix):")
                    self.log(f"  PATH: {file_path}")
                    for fix in fixes_applied:
                        self.log(f"    - {fix}")

    def _fix_invalid_chars(self, path_str: str) -> str:
        """Replace invalid characters with safe alternatives."""
        result = path_str
        for char, replacement in self.CHAR_REPLACEMENTS.items():
            result = result.replace(char, replacement)
        return result

    def _shorten_filename(self, filename: str) -> str:
        """Shorten a filename to fit within MAX_FILENAME_LENGTH."""
        if len(filename) <= self.MAX_FILENAME_LENGTH:
            return filename

        # Separate name and extension
        stem = Path(filename).stem
        ext = Path(filename).suffix

        # Apply word replacements
        for old, new in self.WORD_REPLACEMENTS.items():
            stem = stem.replace(old, new)

        # If still too long, truncate intelligently
        max_stem_length = self.MAX_FILENAME_LENGTH - len(ext)
        if len(stem) > max_stem_length:
            # Try to keep track number at beginning
            track_match = re.match(r'^(\d+[\s\-\.]*)', stem)
            if track_match:
                track_num = track_match.group(1)
                remaining_length = max_stem_length - len(track_num)
                stem = track_num + stem[len(track_num):len(track_num) + remaining_length]
            else:
                stem = stem[:max_stem_length]

        return stem + ext

    def print_summary(self):
        """Print summary of fixes applied."""
        self.log(f"\n{'='*70}")
        self.log("SUMMARY")
        self.log(f"{'='*70}")

        if self.dry_run:
            self.log("\n⚠ DRY RUN - No files were modified")

        self.log(f"\nStatistics:")
        self.log(f"  Files that would be renamed: {len(self.fixed_files)}")
        self.log(f"  Files with errors: {len(self.failed_files)}")

        if self.stats:
            self.log(f"\nFixes that would be applied:" if self.dry_run else f"\nFixes applied:")
            for fix_type, count in sorted(self.stats.items()):
                fix_name = fix_type.replace('_', ' ').title()
                self.log(f"  {fix_name}: {count}")

        # Show paths that are too long
        if self.paths_too_long:
            self.log(f"\n⚠ PATHS TOO LONG (require manual intervention):")
            self.log(f"  Total: {len(self.paths_too_long)} files exceed 60 character path limit")
            self.log(f"\n  First 20 examples:")
            for orig_path, new_path, length in self.paths_too_long[:20]:
                self.log(f"    [{length} chars] {new_path}")
            if len(self.paths_too_long) > 20:
                self.log(f"  ... and {len(self.paths_too_long) - 20} more")
            self.log(f"\n  Suggestions for fixing:")
            self.log(f"    - Manually rename parent folders to be shorter")
            self.log(f"    - Move files to shallower directory structure")
            self.log(f"    - Reorganize content into multiple USB drives")

        # Show failures
        if self.failed_files:
            self.log(f"\n⚠ Files with errors (first 10):")
            for file_path, error in self.failed_files[:10]:
                self.log(f"  {file_path}: {error}")
            if len(self.failed_files) > 10:
                self.log(f"  ... and {len(self.failed_files) - 10} more")

        self.log(f"\n{'='*70}")
        if self.dry_run:
            self.log("To apply these fixes, run with --apply flag")
        else:
            self.log("✓ Fixes have been applied!")
        self.log(f"{'='*70}")


def setup_logging() -> str:
    """Set up logging to timestamped file."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"volvo_path_fixer_{timestamp}.log"

    logger = logging.getLogger('VolvoPathFixer')
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('%(message)s')
    file_handler.setFormatter(file_formatter)

    logger.addHandler(file_handler)

    return str(log_file)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Fix filename and character issues based on Volvo USB verifier CSV report',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview changes)
  python volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/

  # Apply changes
  python volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/ --apply

Note: This script only fixes filename length and invalid character issues.
      Path length issues must be handled manually.

WARNING: Always backup your files before running with --apply!
        """
    )

    parser.add_argument('csv_file', help='CSV file from volvo_usb_verifier.py')
    parser.add_argument('drive_path', help='Path to USB drive or media folder')
    parser.add_argument('--apply', action='store_true',
                       help='Apply fixes (default is dry run)')

    args = parser.parse_args()

    # Validate inputs
    if not os.path.exists(args.csv_file):
        print(f"ERROR: CSV file not found: {args.csv_file}")
        sys.exit(1)

    if not os.path.exists(args.drive_path):
        print(f"ERROR: Drive path not found: {args.drive_path}")
        sys.exit(1)

    # Set up logging
    log_file = setup_logging()
    print(f"Logging to: {log_file}\n")

    # Run fixer
    dry_run = not args.apply
    fixer = VolvoPathFixer(args.csv_file, args.drive_path, dry_run=dry_run)
    fixer.fix_all()

    print(f"\nLog file saved to: {log_file}")


if __name__ == "__main__":
    main()
