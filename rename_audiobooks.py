#!/usr/bin/env python3
"""
Rename audiobook files using Claude CLI for intelligent path shortening.

Usage:
    python rename_audiobooks.py                    # Dry run (preview changes)
    python rename_audiobooks.py --apply            # Actually rename files
    python rename_audiobooks.py --test             # Run tests first
    python rename_audiobooks.py --limit 10         # Process only first 10 files
"""

import subprocess
import os
import sys
import shutil
from pathlib import Path
from collections import defaultdict

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


def get_shortened_path(original_path, base_dir):
    """Use Claude CLI to get shortened path for a file."""
    # Get path relative to base_dir for the prompt
    try:
        rel_path = Path(original_path).relative_to(Path(base_dir).parent)
    except ValueError:
        # If not relative, use as-is
        rel_path = original_path

    # Format path with backslashes for consistency with examples
    prompt_path = str(rel_path).replace('/', '\\')
    prompt = V7_PROMPT.format(path=prompt_path)

    try:
        result = subprocess.run(
            ['claude', '--print', prompt],
            capture_output=True,
            text=True,
            timeout=30,
            encoding='utf-8'
        )

        output = result.stdout.strip()

        # Extract clean path from output
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
                return cleaned

        # Fallback to last line
        if lines:
            cleaned = lines[-1].replace('`', '').replace('**', '').strip()

            # Don't return error messages
            if 'error' in cleaned.lower() or 'timeout' in cleaned.lower():
                return None

            if ':' in cleaned:
                cleaned = cleaned.split(':', 1)[1].strip()
            return cleaned

        return None

    except subprocess.TimeoutExpired:
        print(f"  ERROR: Timeout processing {original_path}")
        return None
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def find_audiobook_files(base_dir):
    """Find all audiobook files in the directory."""
    return sorted(Path(base_dir).rglob("*.mp3"))


def preview_changes(base_dir, limit=None):
    """Preview what changes would be made without actually renaming."""
    files = find_audiobook_files(base_dir)

    if limit:
        files = files[:limit]

    print(f"Found {len(files)} audiobook files to process")
    print(f"{'='*100}\n")

    changes = []
    errors = []
    skipped = []

    for i, file_path in enumerate(files, 1):
        rel_path = file_path.relative_to(Path(base_dir).parent)
        print(f"[{i}/{len(files)}] Processing: {rel_path}")

        shortened = get_shortened_path(file_path, base_dir)

        if not shortened:
            errors.append(str(rel_path))
            print(f"  [ERROR] Could not generate shortened path\n")
            continue

        # Normalize paths for comparison
        original_normalized = str(rel_path).replace('\\', '/')
        shortened_normalized = shortened.replace('\\', '/')

        if original_normalized == shortened_normalized:
            skipped.append(str(rel_path))
            print(f"  [SKIP] Already optimal\n")
            continue

        new_path = Path(base_dir).parent / shortened

        changes.append({
            'original': file_path,
            'new': new_path,
            'original_rel': str(rel_path),
            'new_rel': shortened
        })

        print(f"  [OK] FROM: {rel_path}")
        print(f"       TO:   {shortened}\n")

    # Summary
    print(f"\n{'='*100}")
    print("SUMMARY")
    print(f"{'='*100}")
    print(f"Total files:      {len(files)}")
    print(f"To be renamed:    {len(changes)}")
    print(f"Already optimal:  {len(skipped)}")
    print(f"Errors:           {len(errors)}")

    if errors:
        print(f"\nFiles with errors:")
        for error in errors:
            print(f"  - {error}")

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
            print(f"[{i}/{len(changes)}] {change['original_rel']}")
            print(f"          → {change['new_rel']}")

            # Check if target already exists
            if change['new'].exists():
                print(f"  [WARNING] Target exists, skipping")
                failed += 1
                continue

            # Move the file
            shutil.move(str(change['original']), str(change['new']))
            print(f"  [SUCCESS]\n")
            success += 1

        except Exception as e:
            print(f"  [ERROR] {e}\n")
            failed += 1

    # Cleanup empty directories
    print(f"\nCleaning up empty directories...")
    cleanup_empty_dirs(base_dir)

    print(f"\n{'='*100}")
    print(f"COMPLETE: {success} renamed, {failed} failed")
    print(f"{'='*100}")


def cleanup_empty_dirs(base_dir):
    """Remove empty directories after moving files."""
    # Walk from bottom up to remove nested empty dirs
    for root, dirs, files in os.walk(base_dir, topdown=False):
        for dir_name in dirs:
            dir_path = Path(root) / dir_name
            try:
                if not any(dir_path.iterdir()):  # Check if empty
                    dir_path.rmdir()
                    print(f"  Removed: {dir_path.relative_to(Path(base_dir).parent)}")
            except OSError:
                pass  # Directory not empty or other error


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Rename audiobook files using Claude CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python rename_audiobooks.py                 # Preview changes
  python rename_audiobooks.py --apply         # Apply changes
  python rename_audiobooks.py --limit 5       # Preview first 5 files only
  python rename_audiobooks.py --apply --limit 5   # Apply to first 5 files
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
    if args.limit:
        print(f"Limit: First {args.limit} files only")
    print()

    # Preview changes
    changes = preview_changes(base_dir, limit=args.limit)

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
