#!/usr/bin/env python3
"""
Sample one file from each top-level directory to preview rename patterns.
"""

import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from rename_audiobooks import get_shortened_path, V7_PROMPT

def sample_files(books_dir):
    """Get one sample file from each top-level directory."""
    books_path = Path(books_dir)
    samples = []

    # Get all top-level directories
    top_dirs = sorted([d for d in books_path.iterdir() if d.is_dir()])

    for top_dir in top_dirs:
        # Find first mp3 in this directory tree
        mp3_files = list(top_dir.rglob("*.mp3"))
        if mp3_files:
            samples.append(mp3_files[0])  # Just take the first one

    return samples

def main():
    books_dir = Path(__file__).parent / "VOLVO" / "books"

    if not books_dir.exists():
        print(f"ERROR: {books_dir} not found")
        return

    print(f"Sampling audiobook files from {books_dir}")
    print(f"{'='*100}\n")

    samples = sample_files(books_dir)
    print(f"Found {len(samples)} top-level directories\n")

    for i, file_path in enumerate(samples, 1):
        rel_path = file_path.relative_to(books_dir.parent)
        print(f"[{i}/{len(samples)}] {rel_path}")

        shortened = get_shortened_path(file_path, books_dir)

        if shortened:
            print(f"         -> {shortened}\n")
        else:
            print(f"         -> [ERROR]\n")

    print(f"{'='*100}")
    print(f"Sample complete - tested {len(samples)} directories")
    print(f"{'='*100}")

if __name__ == "__main__":
    main()
