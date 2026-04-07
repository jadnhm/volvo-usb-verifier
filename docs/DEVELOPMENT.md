# Volvo XC70 2012 USB Media Project - Development Guide

## Project Overview

This project provides a complete toolchain for preparing USB drives with media files for the 2012 Volvo XC70 base stereo system. The stereo has very specific requirements that are not well documented, and files that play perfectly on computers often fail in the car.

## Problem Statement

The 2012 Volvo XC70 base stereo is extremely strict about:
- Filesystem format (FAT32 only, MBR partition scheme)
- File and folder structure limits
- Audio file encoding (CBR strongly preferred over VBR)
- ID3 tag versions (ID3v2.3 with ISO-8859-1 encoding)
- Path and filename lengths
- Extended ASCII characters in filenames

Files that work everywhere else often fail silently or cause the entire USB drive to be unreadable.

## Project Architecture

The project consists of two main toolsets:

### Volvo USB Media Preparation Pipeline

The main toolchain now includes dedicated cleanup, verification, rename, conversion, metadata-fix, folder-splitting, and coordination scripts:

### 1. `lib/volvo_usb_verifier.py` - Detection Script

**Purpose**: Scan a USB drive and identify all compatibility issues.

**Key Features**:
- Multithreaded scanning (uses CPU thread count × 2)
- Cross-platform filesystem verification (Windows/Linux/macOS)
- Checks 50+ different compatibility issues
- Exports comprehensive CSV report for downstream processing
- Dual output: console + timestamped log file

**What It Checks**:
- **Filesystem**: FAT32, MBR partition, 32KB clusters
- **Structure**: 15K file max, 1K root folders, 254 files/folder, 8 nesting levels
- **Paths**: Max 60 characters per path, max 64 chars per filename
- **Characters**: Extended ASCII characters that may cause issues
- **Audio**: MP3/WMA/AAC/M4A/M4B formats (FLAC/OGG/WAV unsupported)
- **MP3 Encoding**: CBR vs VBR, bitrate 32-320 kbps (144 kbps forbidden)
- **Sample Rate**: 32/44.1/48 kHz for MP3, 8-96 kHz for AAC
- **ID3 Tags**: Version detection (2.3 preferred, 2.4 problematic)
- **Album Art**: Size estimation (>750KB can cause issues)
- **Track Numbers**: Missing MP3 `TRCK` / M4A `trkn` tags that can cause album tracks to sort badly in-car

**CSV Output Format**:
```csv
file_path,issue_type,severity,description
audiobooks\The Hobbit\file.mp3,Path Length,ERROR,Path length 88 exceeds maximum 60
music\Artist\Song.mp3,ID3 Tags,WARNING,ID3v2.4 (ID3v2.3 recommended)
```

**Issue Types Exported**:
- `Path Length` - Paths over 60 characters
- `Filename Length` - Filenames over 64 characters
- `Invalid Characters` - Extended ASCII (é, ñ, ×, etc.)
- `ID3 Tags` - Wrong version or no tags
- `Album Art` - Oversized embedded images
- `Encoding` - VBR instead of CBR
- `Sample Rate` - Outside supported range
- `Bitrate` - Outside 32-320 kbps or exactly 144 kbps
- `Read Error` - Corrupted files

**Usage**:
```bash
python lib/volvo_usb_verifier.py D:/
```

**Output Files**:
- `logs/volvo_verify_drive_YYYYMMDD_HHMMSS.log` - Full text log
- `logs/volvo_verify_drive_YYYYMMDD_HHMMSS.csv` - Machine-readable issues

**Performance**:
- Processes ~37K files in 3 minutes on modern hardware
- Uses 32 threads on 16-core system

---

### 2. `lib/volvo_usb_fixer.py` - ID3 Tag Fixer

**Purpose**: Automatically fix ID3 tag issues without re-encoding audio.

**Key Features**:
- Multithreaded processing (32 threads)
- Thread-safe operations with locks
- Dry run mode by default (--apply flag for actual changes)
- Real-time per-file output showing what was fixed
- Uses mutagen library for lossless metadata editing

**What It Fixes**:
1. **No ID3 tags** → Adds basic ID3v2.3 tags (title from filename)
2. **ID3v2.4 tags** → Converts to ID3v2.3 with ISO-8859-1 encoding
3. **Unusual ID3 versions** (2.2, etc.) → Converts to ID3v2.3
4. **Large MP3 album artwork** → Removes oversized embedded images
5. **Large M4A album artwork** → Removes oversized `covr` artwork from AAC/M4A files

**Important**: Saves files with BOTH ID3v1 and ID3v2.3 tags per Volvo specs: "Including both ID3v1 and ID3v2.3 tags provides the best fallback behavior"

**What It Does NOT Fix**:
- Encoding issues (VBR → CBR requires re-encoding, lossy operation)
- Sample rate issues (requires re-encoding)
- Bitrate issues (requires re-encoding)
- Missing track numbers (currently verifier-only; useful as a warning for album ordering)
- Path/filename issues (handled by separate script)

**Input**: CSV file from `lib/volvo_usb_verifier.py`

**Workflow Note**: This script resolves files by the exact `file_path` values stored in the verifier CSV. If `lib/volvo_path_fixer.py` has renamed files since that CSV was generated, this script can report "File not found" for the old paths. Re-run the verifier after any applied renames and use the fresh CSV here.

**Usage**:
```bash
# Dry run (preview changes)
python lib/volvo_usb_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/

# Apply changes
python lib/volvo_usb_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/ --apply
```

**Output Example**:
```
✓ [1/14372] audiobooks\file.mp3
    - Converted ID3v2.4 to ID3v2.3
✓ [2/14372] music\artist\song.mp3
    - Removed large album artwork
```

**Performance**: Processes ~14K files with ID3 issues in ~5 minutes

---

### 3. `lib/volvo_path_fixer.py` - Path/Filename Fixer

**Purpose**: Automatically fix filename length and invalid character issues by renaming files. It also reports path length issues that still require manual intervention.

**Key Features**:
- Intelligent abbreviation system
- Preserves track numbers at beginning of filenames
- Dry run mode by default
- Creates parent directories as needed
- Writes a timestamped rename manifest to `logs/` so downstream steps can see exactly what changed

**What It Fixes**:
1. **Invalid characters** - Replaces extended ASCII with safe alternatives
   - é → e, ñ → n, × → x, ½ → 1-2, etc.
2. **Long filenames** - Shortens filenames over 64 characters
   - Applies abbreviations: "Remastered" → "Rmstr", "Deluxe" → "Dlx"
   - Removes "The " prefix
   - Preserves track numbers
3. **Rename manifest** - Records every processed file in `logs/volvo_path_manifest_YYYYMMDD_HHMMSS.csv`
    - Captures original path, new path, status, warnings, and errors
    - Keeps the verifier CSV immutable as a snapshot of scan results
    - Makes it obvious when a fresh verifier CSV is needed before running the ID3 fixer

**Abbreviation Dictionary**:
```python
'The ' → ''
' and ' → ' & '
'featuring' → 'ft'
'Live' → 'Lv'
'Version' → 'Ver'
'Original' → 'Orig'
'Remastered' → 'Rmstr'
'Deluxe' → 'Dlx'
'Edition' → 'Ed'
'Anniversary' → 'Anniv'
```

**Input**: CSV file from `lib/volvo_usb_verifier.py`

**Important Behavior**:
- This script uses the verifier CSV as input.
- When run with `--apply`, it can rename files so the original verifier CSV becomes stale for later steps.
- After applied renames, run `lib/volvo_usb_verifier.py` again before using `lib/volvo_usb_fixer.py`.

**Usage**:
```bash
# Dry run (preview changes)
python lib/volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/

# Apply changes
python lib/volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/ --apply
```

**Output Example**:
```
Would rename:
  FROM: audiobooks\The Hobbit Audiobook\The Hobbit (Disc 01)\1-01 Ch 1a, An Unexpected Party.mp3
    TO:   audiobooks\The Hobbit Audiobook\The Hobbit (Disc 01)\1-01 Ch 1a, Unexpected Party.mp3
    - Replaced invalid characters
        - Shortened filename to 41 chars
```

**Important**: Always run in dry run mode first to review changes!

**Manifest Output**:
```csv
timestamp,source_csv,original_path,new_path,status,actions,warnings,error
2026-04-06T10:15:03,logs/volvo_verify_drive_20260406_101500.csv,music\Artist\Long Name.mp3,music\Artist\Short Name.mp3,renamed,Shortened filename to 60 chars,,
2026-04-06T10:15:04,logs/volvo_verify_drive_20260406_101500.csv,books\Deep\Path\File.mp3,books\Deep\Path\File.mp3,warning_only,,⚠ WARNING: Path is 88 chars (exceeds 60 limit),
```

### Workflow Findings (April 2026)

- `lib/volvo_path_fixer.py` and `lib/volvo_usb_fixer.py` both consume the verifier CSV as input.
- Running the ID3 fixer before the path fixer is safe because it edits files in place and does not change their paths.
- Running the path fixer with `--apply` before the ID3 fixer can make the original verifier CSV stale.
- The correct pipeline after renames is: verify -> path fixer -> re-verify -> ID3 fixer.
- The verifier CSV should be treated as an immutable scan snapshot. Rename operations should be recorded in a separate manifest instead of rewriting the original CSV.
- `lib/volvo_usb_fixer.py` now warns when it detects a newer path manifest than the verifier CSV being used.
- `volvo_pipeline.py` coordinates the preferred workflow end-to-end and automatically feeds the fresh verifier CSV into the ID3 fixer.
- `lib/volvo_usb_cleaner.py` removes common junk files safely before verification.
- `lib/volvo_converter.py` now supports `--resume` so interrupted conversion runs can continue without reprocessing already-converted files.
- `lib/volvo_folder_splitter.py` fixes the 254-files-per-folder limit by moving tracks into numbered subfolders; after using it, the pipeline should be restarted from the beginning.

---

### Audiobook File Renaming Toolset

A separate set of AI-powered tools for intelligently shortening audiobook file paths:

#### `rename_audiobooks_batch.py` - Batch Renaming Script (RECOMMENDED)

**Purpose**: Efficiently rename audiobooks by processing entire books at once instead of individual files.

**Key Features**:
- **93% reduction in API calls** - Groups files by book/directory
- Automatic retry logic with exponential backoff (3 attempts: 30s, 45s, 60s timeouts)
- Dry run mode by default (`--apply` flag for actual changes)
- Example-driven prompt engineering (v7_refined prompt achieves 100% test accuracy)
- Intelligent pattern application across all files in a book

**How It Works**:
1. Groups files by their book/series directory structure
2. Samples one representative file per book
3. Sends sample to Claude to learn the renaming pattern
4. Applies pattern to all files in that book
5. Dramatically reduces cost and time

**Efficiency**:
- 100 files across 7 books = 7 API calls (not 100)
- ~$0.03 for 3,688 files (vs ~$1.50 per-file approach)
- 10-20x faster than per-file processing

**Retry Logic**:
- Automatically retries failed calls up to 3 times
- Exponential backoff: 1s, 2s, 4s delays
- Increasing timeouts: 30s, 45s, 60s
- Recovers ~80% of transient timeout failures

**Usage**:
```bash
# Dry run (default)
python rename_audiobooks_batch.py

# Preview first 100 files
python rename_audiobooks_batch.py --limit 100

# Apply changes
python rename_audiobooks_batch.py --apply
```

**Performance**:
- API call efficiency: 93% reduction
- Success rate: ~98% with retry logic
- Tested on 100 files with excellent results

---

#### `rename_audiobooks.py` - Per-File Renaming Script

**Purpose**: Process each file individually for maximum control.

**Key Features**:
- One API call per file for fine-grained control
- Same v7_refined prompt as batch script
- Best for small batches or unusual edge cases

**Usage**:
```bash
# Dry run (default)
python rename_audiobooks.py

# Apply changes
python rename_audiobooks.py --apply

# Limit to first N files
python rename_audiobooks.py --limit 50
```

**When to Use**:
- Small number of files (<20)
- Files with unusual patterns not fitting book groups
- Testing new prompt variations

**Performance**:
- Each file requires one Claude API call (~1-2 seconds)
- 98% success rate on sample of 50 real files
- More expensive but maximum flexibility

#### `test_path_shortening.py` - Test Suite

**Purpose**: Validate path shortening prompts against known test cases.

**Key Features**:
- 10 comprehensive test cases covering diverse scenarios
- Tests multiple prompt variations (v1-v7)
- Measures match rate percentage
- Detailed mismatch reporting

**Test Cases Cover**:
- Simple single books (1984)
- Books with author in directory (Brave New World)
- Series with years (Harry Potter)
- Multi-disc books (The Hobbit)
- Multi-part books (Roald Dahl)
- Complex series/trilogies (William Gibson)
- Already-simple paths (Gulliver's Travels)
- Double-digit track numbers

**Usage**:
```bash
# Run all prompts against all test cases
python test_path_shortening.py

# Test specific prompt
python test_path_shortening.py v7_refined
```

**Test Results**:
- v7_refined: 10/10 (100%)
- v4_minimal_examples: 4/7 (57%)
- v1_contextual: 4/7 (57%)

#### `sample_rename_preview.py` - Sampling Tool

**Purpose**: Quick preview by testing one file from each top-level directory.

**Key Features**:
- Samples one MP3 from each author/series directory
- Fast way to validate prompt across entire library
- Useful for spotting patterns that need additional test cases

**Usage**:
```bash
python sample_rename_preview.py
```

**Output Example**:
```
[1/12] books\1984 (George Orwell) - Audio Book\...
         -> books/1984/01.mp3

[2/12] books\Harry Potter (Jim Dale)\...
         -> books/Harry Potter/1997 - HP & Philosopher's Stone/01.mp3
```

---

## Complete Workflow

### Step 1: Verify the Drive
```bash
python volvo_usb_verifier.py D:/
```

This generates:
- `logs/volvo_verify_drive_20260103_162933.log`
- `logs/volvo_verify_drive_20260103_162933.csv`

Review the log to understand issues. The CSV is used by the fixer scripts.

### Step 2: Fix Path/Filename Issues (Optional)
```bash
# Dry run first
python volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/

# If changes look good, apply
python volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/ --apply
```

**Important**:
- This script writes `logs/volvo_path_manifest_YYYYMMDD_HHMMSS.csv` containing the rename plan or applied changes.
- If you apply renames, the original verifier CSV may no longer match the current file paths.

### Step 3: Re-verify After Applied Renames
```bash
python volvo_usb_verifier.py D:/
```

Use the fresh verifier CSV for all downstream steps after any applied renames.

### Step 4: Fix ID3 Tag Issues
```bash
# Dry run first
python volvo_usb_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/

# If changes look good, apply
python volvo_usb_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/ --apply
```

### Step 5: Re-verify
```bash
python volvo_usb_verifier.py D:/
```

Check the new CSV to see remaining issues (encoding, sample rate, etc.).

### Step 6: Test in Vehicle
Always test with a small subset (20-30 files) before loading the full library.

---

## Technical Implementation Details

### Multithreading Architecture

All scripts use `ThreadPoolExecutor` with `as_completed()` for optimal performance:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

num_threads = (os.cpu_count() or 4) * 2  # Thread count × 2

with ThreadPoolExecutor(max_workers=num_threads) as executor:
    future_to_file = {
        executor.submit(process_func, file_path): file_path
        for file_path in file_list
    }

    for future in as_completed(future_to_file):
        result = future.result()
        # Process result
```

### Thread Safety

The ID3 fixer uses locks to protect shared data structures:

```python
import threading

self.stats = defaultdict(int)
self.stats_lock = threading.Lock()

# In worker thread:
with self.stats_lock:
    self.stats['files_modified'] += 1
```

### Windows Console Encoding

All scripts handle Windows UTF-8 encoding issues:

```python
if sys.platform == "win32":
    import io
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
```

### Cross-Platform Filesystem Detection

The verifier uses platform-specific commands:

- **Windows**: `wmic` for drive info
- **Linux**: `findmnt -J` for mount details
- **macOS**: `diskutil info` for volume info

### ID3 Tag Manipulation

Uses mutagen library for lossless tag editing:

```python
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, Encoding

audio = MP3(file_path)

# Convert all frames to LATIN1 encoding
for frame in audio.tags.values():
    if hasattr(frame, 'encoding'):
        frame.encoding = Encoding.LATIN1

# Save with both ID3v1 and ID3v2.3
audio.save(v1=2, v2_version=3)
```

---

## Test Data

From the D: drive scan (2026-01-03):

**Total Files**: 36,919 (exceeds 15K limit by 21,919)

**Issue Breakdown**:
- Path Length: 29,699 files (paths over 60 chars)
- ID3 Tags: 11,844 files (wrong version or missing)
- Read Error: 2,936 files (corrupted, can't fix)
- Encoding: 1,359 files (VBR instead of CBR)
- Sample Rate: 940 files (outside 32/44.1/48 kHz)
- Filename Length: 291 files (over 64 chars)
- Bitrate: 212 files (outside 32-320 kbps or exactly 144)
- Album Art: 70 files (oversized images)
- Invalid Characters: 57 files (extended ASCII)
- Unsupported Formats: 38 FLAC files

**Total CSV Entries**: 55,420 problem files

**Recommended Action**:
1. Split into multiple USB drives (need to remove ~22K files to get under 15K limit)
2. Fix path/filename issues (~30K files)
3. Fix ID3 tags (~12K files)
4. Consider re-encoding VBR files to CBR (~1.4K files)
5. Delete or convert 38 FLAC files

---

## Known Limitations

### What Can Be Fixed Automatically
- ✅ ID3 tag versions (lossless)
- ✅ Path/filename lengths (by renaming)
- ✅ Invalid characters (by replacing)
- ✅ Album artwork (by removing)

### What Cannot Be Fixed Automatically
- ❌ VBR → CBR (requires re-encoding, lossy)
- ❌ Sample rate issues (requires re-encoding)
- ❌ Bitrate issues (requires re-encoding)
- ❌ Corrupted files (read errors)
- ❌ File count over 15K (manual curation needed)
- ❌ Filesystem format (requires reformatting drive)

### Path Fixer Limitations
- Currently NOT multithreaded (could be added)
- Renames files individually (could batch rename directories)
- Doesn't detect directory rename conflicts
- May need multiple passes to fully shorten deeply nested paths

---

## Dependencies

### Required Python Packages

For Volvo USB tools:
```bash
pip install mutagen
```

For audiobook renaming tools:
```bash
# Claude CLI (see https://github.com/anthropics/claude-code)
# Requires Claude API access
```

### System Requirements
- Python 3.7 or higher
- Works on Windows, Linux, macOS
- Claude API key (for audiobook renaming tools only)

### Optional Tools for Manual Fixing
- **MP3tag** - ID3 tag editor (https://www.mp3tag.de/)
- **foobar2000** - Audio format converter (https://www.foobar2000.org/)
- **Rufus** - USB formatter for drives >32GB (https://rufus.ie)
- **MediaInfo** - Detailed file inspection (https://mediaarea.net/)

---

## Key Volvo XC70 2012 Specifications

From `Volvo-stereo.md` research:

### Filesystem
- FAT32 only (not NTFS or exFAT)
- MBR partition scheme (not GPT)
- 32KB cluster size recommended
- 32GB or smaller drives guaranteed compatible
- 64GB sometimes works, 128GB mixed results, 512GB almost certainly too large

### File Limits
- **15,000 total files** maximum
- **1,000 folders** in root directory
- **254 files per folder** maximum
- **8 levels** of nesting maximum
- **~60 characters** path length maximum
- **64 characters** filename length maximum (including extension)

### Audio Formats
- **Supported**: MP3, WMA, AAC, M4A, M4B
- **Unsupported**: FLAC, OGG, WAV

### MP3 Requirements
- **CBR encoding strongly recommended** (VBR often fails)
- Bitrate: 32-320 kbps
- **144 kbps explicitly forbidden**
- Sample rate: 32, 44.1, or 48 kHz
- ID3v2.3 with ISO-8859-1 encoding preferred
- Including both ID3v1 and ID3v2.3 provides best fallback

### AAC Requirements
- Sample rate: 8-96 kHz
- No DRM (m4p files won't work)

### Special Notes
- Amazon MP3 files from 2013+ use LAME 3.99 with problematic VBR headers
- Extended ASCII characters (ü, é, ñ) may cause files to be skipped
- Album artwork should be 500×500 pixels or smaller
- The system was designed when 8-16GB drives were standard

---

## Future Improvements

### Path Fixer Enhancements
1. **Add multithreading** - Use ThreadPoolExecutor like other scripts
2. **Batch directory renames** - Rename entire folders instead of individual files
3. **Conflict detection** - Warn when shortening creates duplicate names
4. **Smart abbreviation** - Machine learning to predict best abbreviations
5. **Multiple passes** - Automatically re-run until all paths are short enough

### Verifier Enhancements
1. **VBR header repair** - Integrate MP3Packer/WinMP3Packer functionality
2. **FLAC conversion** - Automatic conversion to CBR MP3
3. **Interactive mode** - Let user choose which issues to fix
4. **Web UI** - Browser-based interface for non-technical users

### General Improvements
1. **Single unified fixer** - Combine ID3 and path fixers into one script
2. **Undo functionality** - Keep backup mapping of all renames/changes
3. **Configuration file** - Let users customize abbreviations, thresholds
4. **Progress persistence** - Save state, resume interrupted operations
5. **GUI wrapper** - Desktop application with drag-and-drop

---

## Git Repository Structure

```
.
├── volvo_usb_verifier.py        # Main detection script
├── volvo_usb_fixer.py           # ID3 tag fixer
├── volvo_path_fixer.py          # Path/filename fixer
├── rename_audiobooks.py         # AI-powered audiobook path shortener
├── test_path_shortening.py      # Test suite for audiobook renaming
├── sample_rename_preview.py     # Quick sampling tool
├── Volvo-stereo.md              # Research/specifications
├── README.md                    # User documentation
├── DEVELOPMENT.md               # This file (development docs)
├── AUDIOBOOK_RENAMING.md        # Audiobook renaming documentation
├── .gitignore                   # Excludes logs/, *.log, test outputs
├── VOLVO/                       # Test data directory
│   └── books/                   # Audiobook files (3,688 MP3s)
└── logs/                        # Generated by scripts (gitignored)
    ├── volvo_verify_*.log
    ├── volvo_verify_*.csv
    ├── volvo_fixer_*.log
    └── volvo_path_fixer_*.log
```

---

## Contributing

When adding features or fixing bugs:

1. **Maintain backward compatibility** with existing CSV format
2. **Add tests** using representative sample files
3. **Update this document** with implementation details
4. **Preserve dry run mode** as default for safety
5. **Add logging** for all operations
6. **Use thread-safe patterns** for parallel processing
7. **Handle Windows paths** correctly (forward slashes work better)

---

## Support & References

- Original specifications: `Volvo-stereo.md`
- Volvo forums: SwedeSpeed, VolvOwners
- Mutagen documentation: https://mutagen.readthedocs.io/
- Python threading: https://docs.python.org/3/library/concurrent.futures.html

---

## License

This project is provided as-is for personal use. No warranty is provided.

---

## Session Notes

**Last Updated**: 2026-01-04

**Current State**:
- All three Volvo USB scripts functional and tested
- Verifier updated to detect path/filename issues (added 2026-01-03)
- CSV export includes all issue types
- Test data: 55,420 problem files identified on D: drive
- Path fixer created but not yet tested on real data
- **NEW**: Audiobook renaming toolset completed and tested (added 2026-01-04)
  - rename_audiobooks.py - Main AI-powered renaming script
  - test_path_shortening.py - Test suite with 10 test cases (100% passing)
  - sample_rename_preview.py - Quick sampling tool
  - v7_refined prompt achieves 100% test accuracy
  - Tested on 50 real files with 98% success rate
  - Documentation: AUDIOBOOK_RENAMING.md

**Next Steps**:
1. Test path fixer dry run on D: drive
2. Consider multithreading for path fixer
3. Add conflict detection for duplicate names after shortening
4. Document re-encoding workflow for VBR/sample rate issues
5. Create example folder structure for organizing <15K files
6. **Audiobook tools**: Add retry logic for Claude API timeouts
7. **Audiobook tools**: Consider batch processing for better API efficiency
