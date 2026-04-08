#!/usr/bin/env python3
"""
Batch audiobook renaming using Claude CLI for intelligent path shortening.
More efficient than per-file renaming - makes decisions at the book/directory level.

Strategy:
1. Group files by their parent directory structure
2. Send one representative path per book/series to Claude
3. Apply the pattern to all files in that book/series
4. Dramatically reduces API calls and token usage

Example: Instead of 14 API calls for 14 files in "1984 (George Orwell)",
         we make 1 API call and apply the pattern to all 14 files.
"""

import subprocess
import os
import sys
import shutil
from pathlib import Path
from collections import defaultdict
import re

# The winning prompt from testing
V7_PROMPT = """Shorten audiobook path. Remove redundancy, keep hierarchy. Extract part/disc into filename.

Examples:
books\\1984 (George Orwell) - Audio Book\\Audio Books - George Orwell - 1984 - 1 of 14.mp3
→ books/1984/01.mp3

books\\Aldous Huxley's - Brave New World\\Brave New World - 01 of 10.mp3
→ books/Brave New World/01.mp3

books\\Harry Potter (Jim Dale)\\(1997) Harry Potter And The Philosopher's Stone\\Chapter 01 - The Boy Who Lived.mp3
→ books/Harry Potter/1997 - HP & Philosopher's Stone/01.mp3

books\\Harry Potter (Jim Dale)\\(1998) Harry Potter And The Chamber Of Secrets\\Chapter 01 - The Worst Birthday.mp3
→ books/Harry Potter/1998 - HP & Chamber of Secrets/01.mp3

books\\The Hobbit Audiobook\\The Hobbit (Disc 01)\\1-01 Ch 1a, An Unexpected Party.mp3
→ books/Hobbit/1-01.mp3

books\\Roald Dahl Audiobooks\\Roald Dahl - Charlie and the Chocolate Factory\\(Roald Dahl) Charlie and the Chocolate Factory (Part 1) - 01.mp3
→ books/Roald Dahl/Charlie & Chocolate Factory/1-01.mp3

books\\Roald Dahl Audiobooks\\Roald Dahl - Charlie and the Chocolate Factory\\(Roald Dahl) Charlie and the Chocolate Factory (Part 3) - 10.mp3
→ books/Roald Dahl/Charlie & Chocolate Factory/3-10.mp3

books\\William Gibson-Collection\\William Gibson-Blue Ant Trilogy[1-3]\\William Gibson-Blue Ant Trilogy-#1-Pattern Recognition\\Pattern Recognition - 001.mp3
→ books/William Gibson/Blue Ant Trilogy/Pattern Recognition/001.mp3

books\\Gulliver's Travels\\01 Voyage to Liliput.mp3
→ books/Gulliver's Travels/01.mp3

Rules:
- Extract "Part N" or "Disc N" from filename → format as N-tracknum.mp3
- Remove "#1", "[1-3]" etc from directories
- Replace "and"/"And" with "&"
- Drop "Audiobook", "Audio Book", "Collection"
- Remove "The" from start of single book titles (keep for series like "The Hobbit" if standalone)
- Keep years in parentheses for series (e.g., 1997, 1998)
- Abbreviate long book titles in series

Path: {path}
Output (path only, no markdown, no explanation):"""


def extract_track_number(filename):
    """Extract track number from filename for pattern matching."""
    # Match patterns like: 01, 001, 1-01, Chapter 01, Track 01, etc.
    patterns = [
        r'^(\d+-\d+)',           # 1-01 (disc-track)
        r'(\d+) of \d+',          # 1 of 14
        r'Chapter (\d+)',         # Chapter 01
        r'Track (\d+)',           # Track 01
        r'^(\d+)',                # 01 at start
        r'- (\d+)',               # - 01
    ]

    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def get_book_pattern(sample_path, base_dir, max_retries=3):
    """
    Use Claude CLI to get shortened path pattern for a book.
    Retries with exponential backoff on timeouts.
    """
    import time

    try:
        rel_path = Path(sample_path).relative_to(Path(base_dir).parent)
    except ValueError:
        rel_path = sample_path

    # Format path with backslashes for consistency with examples
    prompt_path = str(rel_path).replace('/', '\\')
    prompt = V7_PROMPT.format(path=prompt_path)

    for attempt in range(max_retries):
        try:
            # Increase timeout on retries
            timeout = 30 + (attempt * 15)  # 30s, 45s, 60s

            result = subprocess.run(
                ['claude', '--print', prompt],
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8'
            )

            output = result.stdout.strip()
            lines = [line.strip() for line in output.split('\n') if line.strip()]

            # Find the line that looks like a path
            for line in reversed(lines):
                cleaned = line.replace('`', '').replace('**', '').strip()

                # Skip error messages
                if 'error' in cleaned.lower() or 'timeout' in cleaned.lower():
                    continue

                if 'books/' in cleaned.lower() and '.mp3' in cleaned.lower():
                    # Remove any prefix like "Shortened:" or similar
                    if ':' in cleaned:
                        cleaned = cleaned.split(':', 1)[1].strip()

                    if attempt > 0:
                        print(f"  [Retry {attempt} succeeded]")
                    return cleaned

            # No valid path found in output
            if attempt < max_retries - 1:
                print(f"  [No valid output, retrying {attempt + 1}/{max_retries}...]")
                time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                continue
            return None

        except subprocess.TimeoutExpired:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"  [Timeout, retrying {attempt + 1}/{max_retries} in {wait_time}s...]")
                time.sleep(wait_time)
                continue
            else:
                print(f"  [ERROR] Timeout after {max_retries} attempts")
                return None

        except Exception as e:
            print(f"  [ERROR] {e}")
            return None

    return None


def group_files_by_book(files, base_dir):
    """Group files by their book/series directory structure."""
    groups = defaultdict(list)

    for file_path in files:
        rel_path = file_path.relative_to(Path(base_dir).parent)

        # Get the directory path (everything except filename)
        dir_path = str(rel_path.parent).replace('\\', '/')

        groups[dir_path].append(file_path)

    return groups


def apply_pattern_to_file(original_path, sample_path, pattern_result, base_dir):
    """
    Apply the pattern from a sample file to another file in the same book.

    Strategy:
    1. Extract the directory pattern from sample → result
    2. Extract the filename pattern (how track numbers are formatted)
    3. Apply to the target file
    """
    # Get relative paths
    orig_rel = original_path.relative_to(Path(base_dir).parent)
    sample_rel = Path(sample_path).relative_to(Path(base_dir).parent)

    # Parse the pattern result to understand directory and filename structure
    pattern_parts = pattern_result.replace('\\', '/').split('/')
    sample_parts = str(sample_rel).replace('\\', '/').split('/')
    orig_parts = str(orig_rel).replace('\\', '/').split('/')

    # Build new path by:
    # 1. Using the directory pattern from the result
    # 2. Extracting track number from original filename
    # 3. Applying the filename pattern from the result

    # Get new directory structure (all but last part)
    new_dir_parts = pattern_parts[:-1]

    # Get filename pattern from result
    result_filename = pattern_parts[-1]

    # Extract track number from original filename
    orig_filename = orig_parts[-1]
    track_num = extract_track_number(orig_filename)

    if track_num:
        # Build new filename using the track number
        # Check if result has disc-track pattern (e.g., "1-01.mp3")
        if re.match(r'\d+-\d+\.mp3', result_filename):
            if re.match(r'^\d+-\d+$', track_num):
                new_filename = f"{track_num}.mp3"
            else:
            # Preserve disc-track pattern
                # Preserve disc-track pattern
                new_filename = result_filename  # Will be replaced with actual track
                # Extract disc number if present in original
                disc_match = re.search(r'Disc (\d+)|Part (\d+)', str(orig_rel), re.IGNORECASE)
                if disc_match:
                    disc_num = disc_match.group(1) or disc_match.group(2)
                    # Pad track number to match original padding
                    if len(track_num) == 1 and 'of' in orig_filename.lower():
                        track_num = track_num.zfill(2)
                    new_filename = f"{disc_num}-{track_num}.mp3"
                else:
                    # No disc, just use track number with padding from result
                    padding = len(re.search(r'(\d+)\.mp3', result_filename).group(1))
                    new_filename = f"{track_num.zfill(padding)}.mp3"
        else:
            # Simple track number pattern
            # Match padding from result
            padding_match = re.search(r'(\d+)\.mp3', result_filename)
            if padding_match:
                padding = len(padding_match.group(1))
                new_filename = f"{track_num.zfill(padding)}.mp3"
            else:
                new_filename = f"{track_num}.mp3"
    else:
        # Couldn't extract track number, use original filename
        new_filename = orig_filename

    # Combine directory and filename
    new_path_parts = new_dir_parts + [new_filename]
    new_path = '/'.join(new_path_parts)

    return new_path


def find_audiobook_files(base_dir):
    """Find all audiobook files in the directory."""
    return sorted(Path(base_dir).rglob("*.mp3"))


def preview_batch_changes(base_dir, limit=None):
    """Preview changes using batch processing strategy."""
    files = find_audiobook_files(base_dir)

    if limit:
        files = files[:limit]

    print(f"Found {len(files)} audiobook files to process")
    print(f"{'='*100}\n")

    # Group files by book/directory
    groups = group_files_by_book(files, base_dir)
    print(f"Grouped into {len(groups)} books/series")
    print(f"Average {len(files) / len(groups):.1f} files per book\n")
    print(f"Token savings: ~{len(files) - len(groups)} API calls avoided!")
    print(f"{'='*100}\n")

    changes = []
    errors = []
    api_calls = 0

    # Process each group
    for i, (dir_path, group_files) in enumerate(groups.items(), 1):
        print(f"\n[Book {i}/{len(groups)}] {dir_path} ({len(group_files)} files)")

        # Use first file as sample to get pattern
        sample_file = group_files[0]
        sample_rel = sample_file.relative_to(Path(base_dir).parent)

        print(f"  Getting pattern from: {sample_rel}")
        pattern = get_book_pattern(sample_file, base_dir)
        api_calls += 1

        if not pattern:
            print(f"  [ERROR] Could not get pattern")
            for f in group_files:
                errors.append(str(f.relative_to(Path(base_dir).parent)))
            continue

        print(f"  Pattern: {pattern}")

        # Apply pattern to all files in this group
        for file_path in group_files:
            rel_path = file_path.relative_to(Path(base_dir).parent)

            # Apply the pattern
            new_path_str = apply_pattern_to_file(file_path, sample_file, pattern, base_dir)

            # Normalize paths for comparison
            original_normalized = str(rel_path).replace('\\', '/')
            new_normalized = new_path_str.replace('\\', '/')

            if original_normalized == new_normalized:
                continue  # Skip unchanged files

            new_path = Path(base_dir).parent / new_path_str

            changes.append({
                'original': file_path,
                'new': new_path,
                'original_rel': str(rel_path),
                'new_rel': new_path_str
            })

    # Summary
    print(f"\n{'='*100}")
    print("SUMMARY")
    print(f"{'='*100}")
    print(f"Total files:      {len(files)}")
    print(f"Books/Series:     {len(groups)}")
    print(f"API calls made:   {api_calls}")
    print(f"API calls saved:  {len(files) - api_calls} ({100 * (len(files) - api_calls) / len(files):.1f}% reduction)")
    print(f"To be renamed:    {len(changes)}")
    print(f"Errors:           {len(errors)}")

    if errors:
        print(f"\nFiles with errors:")
        for error in errors[:10]:  # Show first 10
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")

    # Show sample changes
    if changes:
        print(f"\n{'='*100}")
        print("SAMPLE CHANGES (first 20)")
        print(f"{'='*100}\n")
        for change in changes[:20]:
            print(f"FROM: {change['original_rel']}")
            print(f"TO:   {change['new_rel']}\n")

    return changes


def apply_changes(changes, base_dir):
    """Actually perform the file renames."""
    print(f"\n{'='*100}")
    print("APPLYING CHANGES")
    print(f"{'='*100}\n")

    success = 0
    failed = 0

    # Group by target directory to create dirs efficiently
    dirs_to_create = set()
    for change in changes:
        dirs_to_create.add(change['new'].parent)

    # Create all needed directories
    print(f"Creating {len(dirs_to_create)} directories...")
    for dir_path in sorted(dirs_to_create):
        dir_path.mkdir(parents=True, exist_ok=True)

    print(f"\nRenaming {len(changes)} files...\n")

    for i, change in enumerate(changes, 1):
        try:
            if i % 100 == 0:  # Progress indicator
                print(f"[{i}/{len(changes)}] Progress...")

            # Check if target already exists
            if change['new'].exists():
                print(f"[WARNING] Target exists: {change['new_rel']}")
                failed += 1
                continue

            # Move the file
            shutil.move(str(change['original']), str(change['new']))
            success += 1

        except Exception as e:
            print(f"[ERROR] {change['original_rel']}: {e}")
            failed += 1

    # Cleanup empty directories
    print(f"\nCleaning up empty directories...")
    cleanup_empty_dirs(base_dir)

    print(f"\n{'='*100}")
    print(f"COMPLETE: {success} renamed, {failed} failed")
    print(f"{'='*100}")


def cleanup_empty_dirs(base_dir):
    """Remove empty directories after moving files."""
    for root, dirs, files in os.walk(base_dir, topdown=False):
        for dir_name in dirs:
            dir_path = Path(root) / dir_name
            try:
                if not any(dir_path.iterdir()):
                    dir_path.rmdir()
                    print(f"  Removed: {dir_path.relative_to(Path(base_dir).parent)}")
            except OSError:
                pass


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Batch rename audiobook files using Claude CLI (more efficient)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python rename_audiobooks_batch.py                 # Preview changes
  python rename_audiobooks_batch.py --apply         # Apply changes
  python rename_audiobooks_batch.py --limit 100     # Preview first 100 files only
        """
    )

    parser.add_argument('--apply', action='store_true',
                       help='Actually rename files (default is dry-run)')
    parser.add_argument('--limit', type=int, metavar='N',
                       help='Only process first N files')
    parser.add_argument('--dir', type=str, default='VOLVO/books',
                       help='Directory to process (default: VOLVO/books)')

    args = parser.parse_args()

    # Determine base directory
    script_dir = Path(__file__).parent
    base_dir = script_dir / args.dir

    if not base_dir.exists():
        print(f"ERROR: Directory not found: {base_dir}")
        sys.exit(1)

    print(f"Processing directory: {base_dir}")
    print(f"Mode: {'APPLY CHANGES' if args.apply else 'DRY RUN (preview only)'}")
    print(f"Strategy: BATCH PROCESSING (one API call per book, not per file)")
    if args.limit:
        print(f"Limit: First {args.limit} files only")
    print()

    # Preview changes
    changes = preview_batch_changes(base_dir, limit=args.limit)

    if not changes:
        print("\nNo changes to apply.")
        return

    # Apply if requested
    if args.apply:
        confirm = input(f"\nProceed with renaming {len(changes)} files? [y/N]: ")
        if confirm.lower() == 'y':
            apply_changes(changes, base_dir)
        else:
            print("Cancelled.")
    else:
        print(f"\n{'='*100}")
        print("DRY RUN COMPLETE - No files were changed")
        print("Run with --apply to actually rename files")
        print(f"{'='*100}")


if __name__ == "__main__":
    main()
