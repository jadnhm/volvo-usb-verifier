# Volvo XC70 2012 USB Media Toolchain

A complete Python toolchain for preparing USB drives with media files for the 2012 Volvo XC70 base stereo system. The stereo has strict requirements that are poorly documented, and files that play perfectly on computers often fail in the car. This toolchain helps identify and fix compatibility issues.

## Project Overview

This project consists of three Python scripts that work together:

1. **`volvo_usb_verifier.py`** - Scans your USB drive and identifies all compatibility issues
2. **`volvo_usb_fixer.py`** - Automatically fixes ID3 tag issues (lossless)
3. **`volvo_path_fixer.py`** - Automatically fixes filename and character issues

## Installation

### Prerequisites

1. **Python 3.7 or higher**
   - Windows: Download from [python.org](https://www.python.org/downloads/)
   - Linux: Usually pre-installed, or use `sudo apt install python3`
   - macOS: Use Homebrew: `brew install python3`

2. **Mutagen library** (for audio file analysis)
   ```bash
   pip install mutagen
   ```

## The Scripts

### 1. volvo_usb_verifier.py - Detection & Analysis

**Purpose**: Scan your USB drive and identify all compatibility issues.

**What It Checks**:
- **Filesystem**: FAT32 (not NTFS/exFAT), MBR partition (not GPT), 32KB clusters
- **File Limits**: 15K max files, 1K root folders, 254 files/folder, 8 nesting levels
- **Paths**: Max 60 chars per path, max 64 chars per filename
- **Characters**: Extended ASCII (é, ñ, ü, etc.) that may cause issues
- **Formats**: MP3/WMA/AAC/M4A supported; FLAC/OGG/WAV unsupported
- **MP3 Encoding**: CBR vs VBR, bitrate 32-320 kbps (144 kbps forbidden)
- **Sample Rate**: 32/44.1/48 kHz for MP3, 8-96 kHz for AAC
- **ID3 Tags**: Version detection (ID3v2.3 preferred, ID3v2.4 problematic)
- **Album Art**: Size estimation (>750KB can cause issues)

**Usage**:
```bash
# Windows
python volvo_usb_verifier.py D:/

# Linux/macOS
python volvo_usb_verifier.py /path/to/usb
```

**Output Files**:
- `logs/volvo_verify_drive_YYYYMMDD_HHMMSS.log` - Human-readable report
- `logs/volvo_verify_drive_YYYYMMDD_HHMMSS.csv` - Machine-readable issue list

**CSV Format**:
```csv
file_path,issue_type,severity,description
audiobooks\file.mp3,Path Length,ERROR,Path length 88 exceeds maximum 60
music\song.mp3,ID3 Tags,WARNING,ID3v2.4 (ID3v2.3 recommended)
```

**Performance**: Processes ~37K files in 3 minutes using multithreading (32 threads on 16-core system).

---

### 2. volvo_usb_fixer.py - ID3 Tag Fixer

**Purpose**: Automatically fix ID3 tag issues without re-encoding audio (lossless operation).

**What It Fixes**:
1. **No ID3 tags** → Adds basic ID3v2.3 tags (title from filename)
2. **ID3v2.4 tags** → Converts to ID3v2.3 with ISO-8859-1 encoding
3. **Unusual ID3 versions** (2.2, etc.) → Converts to ID3v2.3
4. **Large album artwork** → Removes oversized embedded images (>750KB)

**Important**: Saves files with BOTH ID3v1 and ID3v2.3 tags per Volvo specs for best compatibility.

**What It Does NOT Fix**:
- VBR → CBR conversion (requires re-encoding, lossy)
- Sample rate issues (requires re-encoding)
- Bitrate issues (requires re-encoding)
- Path/filename issues (use `volvo_path_fixer.py`)

**Input**: CSV file from `volvo_usb_verifier.py`

**Usage**:
```bash
# Dry run (preview changes)
python volvo_usb_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/

# Apply changes
python volvo_usb_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/ --apply
```

**Output Example**:
```
✓ [1/14372] audiobooks\file.mp3
    - Converted ID3v2.4 to ID3v2.3
✓ [2/14372] music\artist\song.mp3
    - Removed large album artwork
```

**Performance**: Processes ~14K files with ID3 issues in ~5 minutes using multithreading.

---

### 3. volvo_path_fixer.py - Filename & Character Fixer

**Purpose**: Automatically fix filename length and invalid character issues. Reports on path length issues that require manual intervention.

**What It Fixes**:
1. **Long filenames** - Shortens filenames over 64 characters
   - Applies abbreviations: "Remastered" → "Rmstr", "Deluxe" → "Dlx", "The " → ""
   - Removes spaces and special characters
   - Preserves track numbers at beginning
2. **Invalid characters** - Replaces extended ASCII with safe alternatives
   - é → e, ñ → n, ü → u, etc.

**What It Reports (but doesn't fix)**:
- **Path length** - Paths over 60 characters (requires manual folder renaming)

**Character Replacements**:
```
é, è, ê, ë → e
á, à, â, ä → a
í, ì, î, ï → i
ó, ò, ô, ö → o
ú, ù, û, ü → u
ñ → n, ç → c
× → x, ½ → 1-2
```

**Abbreviation Dictionary**:
```
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

**Input**: CSV file from `volvo_usb_verifier.py`

**Usage**:
```bash
# Dry run (preview changes)
python volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/

# Apply changes
python volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/ --apply
```

**Output Example**:
```
Would rename:
  FROM: audiobooks\Harry Potter\Chapter 06 - The Journey From Platform Nine And Three Quarters.mp3
  TO:   audiobooks\Harry Potter\Chapter 06 - Journey From Platform Nine & Three Quarters.mp3
    - Shortened filename to 60 chars

File with issues (cannot fix):
  PATH: audiobooks\The Hobbit Audiobook\The Hobbit (Disc 01)\1-01 Ch 1a, An Unexpected Party.mp3
    - ⚠ WARNING: Path is 88 chars (exceeds 60 limit)
```

**Important**: Always run in dry run mode first to review changes!

---

## Complete Workflow

### Step 1: Format Your USB Drive

**Recommended Settings**:
- **Size**: 32GB or smaller (guaranteed compatible)
- **Filesystem**: FAT32
- **Partition Scheme**: MBR (not GPT)
- **Cluster Size**: 32KB

**Tools**:
- Windows (≤32GB): Built-in Format tool
- Windows (>32GB): [Rufus](https://rufus.ie)
- Linux: `sudo mkfs.vfat -F 32 -s 64 /dev/sdX1`
- macOS: Disk Utility (MS-DOS FAT, MBR)

### Step 2: Copy Files to USB Drive

Organize your files with a simple structure:
```
D:\
├── audiobooks\
│   ├── Author Name\
│   │   └── Book Title\
│   │       └── files.mp3
├── music\
│   ├── Artist Name\
│   │   └── Album Name\
│   │       └── tracks.mp3
└── podcasts\
    └── Podcast Name\
        └── episodes.mp3
```

**Guidelines**:
- Keep folder structure shallow (max 8 levels)
- Use short, simple names
- Avoid special characters
- Stay under 15,000 total files
- Keep under 254 files per folder

### Step 3: Verify the Drive

**Basic Usage** (console output only):
```bash
# Windows
python volvo_usb_verifier.py D:/

# Linux/macOS
python volvo_usb_verifier.py /path/to/usb
```

**Output Files Generated**:
- `logs/volvo_verify_drive_YYYYMMDD_HHMMSS.log` - Full text report (automatically saved)
- `logs/volvo_verify_drive_YYYYMMDD_HHMMSS.csv` - Issue list for fixer scripts

Review the log files to understand all issues found.

### Step 4: Fix Filename Issues (Optional)

**IMPORTANT**: Run this BEFORE the ID3 fixer because renaming files invalidates CSV paths.

**Basic Usage**:
```bash
# Dry run first
python volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/

# Review output, then apply if acceptable
python volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/ --apply
```

**Save Console Output**:

Windows (PowerShell):
```powershell
python volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/ | Tee-Object -FilePath "path_fixer_output.txt"
```

Linux/macOS:
```bash
python volvo_path_fixer.py logs/volvo_verify_drive_20260103_162933.csv /path/to/usb 2>&1 | tee path_fixer_output.txt
```

**What It Does**:

Fixes:
- Long filenames (>64 chars)
- Invalid characters (é, ñ, etc.)

Reports (but doesn't fix):
- Long paths (>60 chars) - requires manual folder renaming

### Step 5: Fix ID3 Tag Issues

**Basic Usage**:
```bash
# Dry run first
python volvo_usb_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/

# Review output, then apply if acceptable
python volvo_usb_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/ --apply
```

**Save Console Output**:

Windows (PowerShell):
```powershell
python volvo_usb_fixer.py logs/volvo_verify_drive_20260103_162933.csv D:/ | Tee-Object -FilePath "id3_fixer_output.txt"
```

Linux/macOS:
```bash
python volvo_usb_fixer.py logs/volvo_verify_drive_20260103_162933.csv /path/to/usb 2>&1 | tee id3_fixer_output.txt
```

**What It Does**:

Fixes:
- Missing ID3 tags
- ID3v2.4 → ID3v2.3 conversion
- Large album artwork removal
- Adds both ID3v1 and ID3v2.3 for compatibility

### Step 6: Re-verify

```bash
python volvo_usb_verifier.py D:/
```

Check the new report to see remaining issues that require manual intervention:
- VBR encoding (requires re-encoding to CBR)
- Sample rate issues (requires re-encoding)
- Bitrate issues (requires re-encoding)
- Path length issues (requires manual folder renaming)
- Too many files (requires splitting across multiple drives)

### Step 7: Handle Remaining Issues Manually

**For VBR/Sample Rate/Bitrate Issues**:
Use [foobar2000](https://www.foobar2000.org/) to re-encode:
1. File → Convert → ...
2. Output format: MP3 (LAME)
3. Encoding: CBR, 192 kbps or 256 kbps
4. Sample rate: 44100 Hz

**For Path Length Issues**:
Manually rename parent folders to be shorter:
- `audiobooks\The Hobbit Audiobook` → `audiobooks\Hobbit`
- `music\Artist Name - Full Album Title (Deluxe Edition)` → `music\Artist\Album`

**For Too Many Files**:
Split content across multiple 32GB USB drives:
- Drive 1: Audiobooks
- Drive 2: Music A-M
- Drive 3: Music N-Z

### Step 8: Test in Vehicle

**IMPORTANT**: Always test with a small subset first!

1. Start with 20-30 representative files
2. Test playback, navigation, and folder browsing
3. If successful, gradually add more content
4. Monitor for any playback issues or skipped files

## What Can/Cannot Be Fixed Automatically

### ✅ Can Be Fixed Automatically (Lossless)
- ID3 tag versions → `volvo_usb_fixer.py`
- Missing ID3 tags → `volvo_usb_fixer.py`
- Large album artwork → `volvo_usb_fixer.py`
- Long filenames → `volvo_path_fixer.py`
- Invalid characters → `volvo_path_fixer.py`

### ❌ Cannot Be Fixed Automatically
- **VBR → CBR** (requires re-encoding, lossy)
- **Sample rate issues** (requires re-encoding)
- **Bitrate issues** (requires re-encoding)
- **Path length** (requires manual folder renaming)
- **Corrupted files** (read errors)
- **File count over 15K** (requires manual curation or multiple drives)
- **Filesystem format** (requires reformatting drive)

## Technical Details

### Multithreading

All scripts use `ThreadPoolExecutor` for optimal performance:
- Verifier: CPU count × 2 threads (e.g., 32 threads on 16-core system)
- ID3 Fixer: 32 threads with thread-safe locks
- Path Fixer: Single-threaded (no concurrency needed for file renaming)

### Cross-Platform Support

All scripts work on Windows, Linux, and macOS:
- Windows: Uses `wmic` for drive info
- Linux: Uses `findmnt -J` for mount details
- macOS: Uses `diskutil info` for volume info

### Logging

All scripts automatically generate timestamped log files in `logs/` directory:

**Automatic Log Files**:
- All scripts save output to `logs/` automatically (no user action needed)
- Verifier: `logs/volvo_verify_drive_YYYYMMDD_HHMMSS.log` + `.csv`
- ID3 Fixer: `logs/volvo_fixer_YYYYMMDD_HHMMSS.log`
- Path Fixer: `logs/volvo_path_fixer_YYYYMMDD_HHMMSS.log`

**Console Output**:
- Real-time progress shown on screen
- Can be saved using `tee` command (see workflow examples)

**Output Options**:
1. **Console only** - Just run the script normally
2. **Console + log file** - Automatic (always happens)
3. **Console + log file + saved console** - Use `tee` command (see Step 3-5 examples)

## Recommended Tools

- **MP3tag**: Manual ID3 tag editing ([mp3tag.de](https://www.mp3tag.de/))
- **foobar2000**: Audio format conversion ([foobar2000.org](https://www.foobar2000.org/))
- **Rufus**: USB drive formatting on Windows ([rufus.ie](https://rufus.ie))
- **MediaInfo**: Detailed file inspection ([mediaarea.net](https://mediaarea.net/))
- **FAT Sorter**: Alphabetize files on FAT32 drives

## Known Issues & Limitations

### Verifier Limitations
- Cannot detect all possible playback issues
- Some filesystem checks require administrator/root privileges
- VBR detection may not catch all problematic encodings
- Album art size is estimated, not precisely measured

### Fixer Limitations
- Path fixer currently NOT multithreaded (could be optimized)
- Path fixer doesn't detect directory rename conflicts
- Path length issues require manual intervention
- Re-encoding issues (VBR, sample rate) must be handled manually

## Troubleshooting

### Script Errors

**"ERROR: Failed to load CSV file"**
- Solution: Ensure CSV file path is correct and file exists
- Check that you ran the verifier script first

**"File not found"** during fixing
- Solution: File may have been moved or deleted since verification
- Re-run the verifier to generate a fresh CSV

**"Permission denied"** errors
- Solution: Run with administrator/sudo privileges
- Or ensure USB drive is not write-protected

### Common Issues

**Verifier runs but shows no issues, but car still won't play files**
- May be VBR encoding issues (not always detected)
- Try re-encoding a few test files as CBR 192 kbps
- Check that drive is properly formatted (FAT32, MBR, 32KB clusters)

**Fixer says it fixed files but issues remain**
- Re-run verifier to generate fresh CSV
- Some issues (path length) cannot be auto-fixed
- Check log files for errors during fixing

**Too slow on large drives**
- Verifier is optimized with multithreading
- Consider processing in batches
- Ensure drive has good USB 3.0 connection

## Contributing

For bug reports, feature requests, or contributions, please see `DEVELOPMENT.md` for detailed technical documentation.

## License

This project is provided as-is for personal use. No warranty is provided.

## References

Based on specifications compiled from:
- Volvo owner forums (SwedeSpeed, VolvOwners)
- 2012 Volvo XC70 owner manual USB specifications
- Real-world testing by Volvo owners
- Extensive research documented in `Volvo-stereo.md`

---

**Last Updated**: 2026-01-03
