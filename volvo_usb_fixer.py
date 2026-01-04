#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Volvo XC70 2012 USB Media File Fixer

This script processes the CSV output from volvo_usb_verifier.py and automatically
fixes common issues to make files compatible with the 2012 Volvo XC70 stereo.

Fixes applied:
- Convert ID3 tags to ID3v2.3 with ISO-8859-1 encoding
- Add basic ID3v2.3 tags to files with no tags
- Remove or resize large album artwork
- (Future: VBR to CBR conversion would require re-encoding)

WARNING: This script modifies files in place. Always backup your files first!
"""

import os
import sys
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Fix Windows console encoding issues
if sys.platform == "win32":
    import io
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, TALB, TDRC, APIC
    from mutagen.id3 import Encoding
except ImportError:
    print("ERROR: This script requires the 'mutagen' library.")
    print("Install it with: pip install mutagen")
    sys.exit(1)


class VolvoUSBFixer:
    """Fixes audio files based on CSV report from volvo_usb_verifier.py"""

    def __init__(self, csv_file: str, drive_path: str, dry_run: bool = True, num_threads: Optional[int] = None):
        self.csv_file = Path(csv_file)
        self.drive_path = Path(drive_path)
        self.dry_run = dry_run
        self.logger = logging.getLogger('VolvoUSBFixer')
        self.num_threads = num_threads or (os.cpu_count() or 4) * 2

        # Statistics (thread-safe)
        self.stats = defaultdict(int)
        self.stats_lock = threading.Lock()
        self.fixed_files = []
        self.fixed_files_lock = threading.Lock()
        self.failed_files = []
        self.failed_files_lock = threading.Lock()

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
                    file_path = row['file_path']
                    issues_by_file[file_path].append(row)

            self.log(f"Loaded issues for {len(issues_by_file)} files from {self.csv_file}")
            return issues_by_file
        except Exception as e:
            self.log(f"ERROR: Failed to load CSV file: {e}")
            sys.exit(1)

    def fix_all(self):
        """Process all files and apply fixes."""
        mode = "DRY RUN" if self.dry_run else "LIVE MODE"
        self.log(f"\n{'='*70}")
        self.log(f"Volvo USB Fixer - {mode}")
        self.log(f"{'='*70}")

        if self.dry_run:
            self.log("\n⚠ DRY RUN: No files will be modified. Use --apply to make changes.")
        else:
            self.log("\n⚠ LIVE MODE: Files will be modified in place!")

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

        # Process files in parallel
        total_files = len(issues_by_file)
        self.log(f"\nProcessing {total_files} files using {self.num_threads} threads...")

        processed = 0
        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            # Submit all file fixing tasks
            future_to_file = {
                executor.submit(self._process_file, file_path, issues): file_path
                for file_path, issues in issues_by_file.items()
            }

            # Process results as they complete
            for future in as_completed(future_to_file):
                processed += 1

                try:
                    result = future.result()
                    # result is a tuple: (file_path, fixes_applied, success)
                    if result:
                        file_path, fixes_applied, success = result
                        if fixes_applied:
                            prefix = "✓" if success else "✗"
                            self.log(f"{prefix} [{processed}/{total_files}] {file_path}")
                            for fix in fixes_applied:
                                self.log(f"    - {fix}")
                        elif not success:
                            self.log(f"✗ [{processed}/{total_files}] {file_path}: No fixes applied")
                except Exception as e:
                    file_path = future_to_file[future]
                    self.log(f"✗ [{processed}/{total_files}] {file_path}: Unexpected error: {e}")
                    with self.failed_files_lock:
                        self.failed_files.append((file_path, f"Unexpected error: {e}"))

        # Print summary
        self.print_summary()

    def _process_file(self, file_path: str, issues: List[Dict]):
        """Process a single file (thread-safe wrapper). Returns (file_path, fixes_applied, success)."""
        full_path = self.drive_path / file_path

        if not full_path.exists():
            with self.failed_files_lock:
                self.failed_files.append((file_path, "File not found"))
            return (file_path, ["File not found"], False)

        # Only process MP3 files for now
        if full_path.suffix.lower() == '.mp3':
            return self.fix_mp3_file(full_path, file_path, issues)

        return None

    def fix_mp3_file(self, full_path: Path, rel_path: str, issues: List[Dict]):
        """Fix issues in an MP3 file. Returns (file_path, fixes_applied, success)."""
        try:
            # Check what types of issues this file has
            issue_types = {issue['issue_type'] for issue in issues}

            # Only process ID3 tag issues for now
            id3_issues = [i for i in issues if 'ID3' in i['issue_type'] or 'Album Art' in i['issue_type']]

            if not id3_issues:
                return (rel_path, [], True)  # Nothing we can fix

            # Load the file
            try:
                audio = MP3(full_path)
            except Exception as e:
                with self.failed_files_lock:
                    self.failed_files.append((rel_path, f"Failed to load MP3: {e}"))
                return (rel_path, [f"Failed to load MP3: {e}"], False)

            modified = False
            fixes_applied = []

            # Handle "No ID3 tags found"
            if any("No ID3 tags found" in i['description'] for i in id3_issues):
                if self.dry_run:
                    fixes_applied.append("Would add basic ID3v2.3 tags")
                else:
                    # Create new ID3v2.3 tags
                    audio.tags = ID3()
                    # Add minimal tags (title from filename)
                    title = full_path.stem
                    audio.tags.add(TIT2(encoding=Encoding.LATIN1, text=title))
                    modified = True
                    fixes_applied.append("Added basic ID3v2.3 tags")
                with self.stats_lock:
                    self.stats['added_tags'] += 1

            # Handle ID3v2.4 -> ID3v2.3 conversion
            elif any("ID3v2.4" in i['description'] for i in id3_issues):
                if self.dry_run:
                    fixes_applied.append("Would convert ID3v2.4 to ID3v2.3")
                else:
                    if audio.tags:
                        # Convert all text frames to LATIN1 encoding
                        for frame in audio.tags.values():
                            if hasattr(frame, 'encoding'):
                                frame.encoding = Encoding.LATIN1
                        modified = True
                        fixes_applied.append("Converted ID3v2.4 to ID3v2.3")
                with self.stats_lock:
                    self.stats['converted_tags'] += 1

            # Handle unusual ID3 versions (2.2, etc.)
            elif any("Unusual ID3 version" in i['description'] for i in id3_issues):
                if self.dry_run:
                    fixes_applied.append("Would convert to ID3v2.3")
                else:
                    if audio.tags:
                        # Convert all text frames to LATIN1 encoding
                        for frame in audio.tags.values():
                            if hasattr(frame, 'encoding'):
                                frame.encoding = Encoding.LATIN1
                        modified = True
                        fixes_applied.append("Converted to ID3v2.3")
                with self.stats_lock:
                    self.stats['converted_unusual_tags'] += 1

            # Handle large album art
            if any("Large artwork" in i['description'] for i in id3_issues):
                if self.dry_run:
                    fixes_applied.append("Would remove large album artwork")
                else:
                    if audio.tags:
                        # Remove all APIC frames (album art)
                        audio.tags.delall('APIC')
                        modified = True
                        fixes_applied.append("Removed large album artwork")
                with self.stats_lock:
                    self.stats['removed_artwork'] += 1

            # Save changes
            if modified:
                try:
                    # Save with BOTH ID3v1 and ID3v2.3 for best compatibility
                    # According to Volvo specs: "Including both ID3v1 and ID3v2.3 tags
                    # provides the best fallback behavior"
                    audio.save(v1=2, v2_version=3)
                    with self.fixed_files_lock:
                        self.fixed_files.append((rel_path, fixes_applied))
                    with self.stats_lock:
                        self.stats['files_modified'] += 1
                    return (rel_path, fixes_applied, True)
                except Exception as e:
                    with self.failed_files_lock:
                        self.failed_files.append((rel_path, f"Failed to save: {e}"))
                    return (rel_path, fixes_applied + [f"Failed to save: {e}"], False)
            elif fixes_applied:
                # Dry run - record what would be done
                with self.fixed_files_lock:
                    self.fixed_files.append((rel_path, fixes_applied))
                return (rel_path, fixes_applied, True)

            return (rel_path, [], True)

        except Exception as e:
            with self.failed_files_lock:
                self.failed_files.append((rel_path, f"Unexpected error: {e}"))
            return (rel_path, [f"Unexpected error: {e}"], False)

    def print_summary(self):
        """Print summary of fixes applied."""
        self.log(f"\n{'='*70}")
        self.log("SUMMARY")
        self.log(f"{'='*70}")

        if self.dry_run:
            self.log("\n⚠ DRY RUN - No files were modified")

        self.log(f"\nStatistics:")
        self.log(f"  Files that would be modified: {len(self.fixed_files)}")
        self.log(f"  Files with errors: {len(self.failed_files)}")

        if self.stats:
            self.log(f"\nFixes that would be applied:" if self.dry_run else f"\nFixes applied:")
            for fix_type, count in sorted(self.stats.items()):
                fix_name = fix_type.replace('_', ' ').title()
                self.log(f"  {fix_name}: {count}")

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
    log_file = log_dir / f"volvo_fixer_{timestamp}.log"

    logger = logging.getLogger('VolvoUSBFixer')
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
        description='Fix audio files based on Volvo USB verifier CSV report',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (preview changes)
  python volvo_usb_fixer.py logs/volvo_verify_drive_20260103_140846.csv D:/

  # Apply changes
  python volvo_usb_fixer.py logs/volvo_verify_drive_20260103_140846.csv D:/ --apply

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
    fixer = VolvoUSBFixer(args.csv_file, args.drive_path, dry_run=dry_run)
    fixer.fix_all()

    print(f"\nLog file saved to: {log_file}")


if __name__ == "__main__":
    main()
