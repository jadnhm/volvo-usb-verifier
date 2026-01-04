# Audiobook File Renaming Tool

## Overview

This toolset uses Claude CLI to intelligently shorten audiobook file paths while preserving essential information and playback order.

## Files

- `rename_audiobooks.py` - Main script for batch renaming files
- `test_path_shortening.py` - Test suite for prompt validation
- `sample_rename_preview.py` - Quick preview of one file per directory
- `AUDIOBOOK_RENAMING.md` - This documentation file

These scripts are located in the project root directory and operate on the `VOLVO/books/` subdirectory by default.

## Usage

**Important:** Run these commands from the project root directory (`Volvo Media Project/`).


### Preview Changes (Dry Run - Default)

```bash
# Preview all changes
python rename_audiobooks.py

# Preview first N files
python rename_audiobooks.py --limit 50

# Preview specific directory
python rename_audiobooks.py --dir VOLVO/books
```

### Apply Changes

```bash
# Actually rename files (with confirmation prompt)
python rename_audiobooks.py --apply

# Apply to first N files
python rename_audiobooks.py --apply --limit 50
```

### Testing

```bash
# Run all test cases
python test_path_shortening.py

# Test specific prompt version
python test_path_shortening.py v7_refined

# Quick sample across all directories
python sample_rename_preview.py
```

## Examples

### Before and After

```
BEFORE: books\1984 (George Orwell) - Audio Book\Audio Books - George Orwell - 1984 - 1 of 14.mp3
AFTER:  books/1984/01.mp3

BEFORE: books\Harry Potter (Jim Dale)\(1997) Harry Potter And The Philosopher's Stone\Chapter 01 - The Boy Who Lived.mp3
AFTER:  books/Harry Potter/1997 - HP & Philosopher's Stone/01.mp3

BEFORE: books\Roald Dahl Audiobooks\Roald Dahl - Charlie and the Chocolate Factory\(Roald Dahl) Charlie and the Chocolate Factory (Part 1) - 01.mp3
AFTER:  books/Roald Dahl/Charlie & Chocolate Factory/1-01.mp3

BEFORE: books\The Hobbit Audiobook\The Hobbit (Disc 01)\1-01 Ch 1a, An Unexpected Party.mp3
AFTER:  books/Hobbit/1-01.mp3

BEFORE: books\Gulliver's Travels\01 Voyage to Liliput.mp3
AFTER:  books/Gulliver's Travels/01.mp3
```

## How It Works

1. **Scans** all .mp3 files in the books directory
2. **Sends** each full path to Claude CLI with a carefully crafted prompt
3. **Receives** shortened path that:
   - Removes redundant text (author names repeated, "Audio Book", etc.)
   - Abbreviates long titles
   - Extracts Part/Disc numbers into filename (e.g., "1-01.mp3")
   - Replaces "and" with "&"
   - Keeps essential hierarchy (Author/Series/Book/Track)
4. **Previews** all changes in dry-run mode
5. **Applies** changes only when confirmed with `--apply`

## Performance

- Tested on 3,688 audiobook files
- Success rate: ~98% on sample of 50 files
- Occasional API timeouts (retryable)
- Each file requires one Claude API call (~1-2 seconds)

## Prompt Strategy

The winning prompt (`v7_refined`) uses:
- **Example-driven learning** - Shows 10 diverse examples
- **Explicit rules** - Clear instructions for edge cases
- **Clean output** - Requests "no markdown, no explanation"
- **Context awareness** - Understands full path hierarchy

Test results:
- v7_refined: 10/10 test cases (100%)
- v4_minimal_examples: 4/7 (57%)
- v1_contextual: 4/7 (57%)

## Safety Features

- **Dry run by default** - Never modifies files without `--apply`
- **Confirmation prompt** - Requires 'y' before applying changes
- **Duplicate detection** - Won't overwrite existing files
- **Empty directory cleanup** - Removes old empty directories after moving files
- **Error logging** - Tracks all failures and timeouts

## Known Issues

1. **Occasional timeouts** - Some API calls timeout (30s limit), can retry
2. **Error responses** - Some responses contain "Execution error" - these are filtered out
3. **Special characters** - Windows console encoding requires ASCII-only status symbols

## Future Improvements

- Add retry logic for timeouts
- Batch API calls for better performance
- Add ability to resume from last processed file
- Generate detailed log file of all changes
