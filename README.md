# Volvo XC70 2012 USB Media Verifier

A Python script to verify that your USB drive and media files meet all the requirements for the 2012 Volvo XC70 base stereo system.

## What It Checks

### Filesystem Requirements
- FAT32 filesystem (not NTFS or exFAT)
- MBR partition scheme (not GPT)
- 32KB cluster size (recommended)

### File Structure Limits
- Maximum 15,000 total audio files
- Maximum 1,000 folders in root directory
- Maximum 254 files per individual folder
- Maximum 8 levels of folder nesting
- Path lengths under 60 characters

### Audio File Requirements
- **Supported formats**: MP3, WMA, AAC, M4A, M4B
- **Unsupported formats**: FLAC, OGG, WAV (will be flagged)

### MP3 Specific Checks
- CBR (constant bitrate) encoding recommended over VBR
- Bitrate: 32-320 kbps (144 kbps explicitly forbidden)
- Sample rate: 32, 44.1, or 48 kHz
- ID3 tags: ID3v2.3 preferred over ID3v2.4
- Album artwork: Should be 500x500 pixels or smaller

### AAC/M4A Checks
- DRM detection (iTunes protected .m4p files)
- Sample rate: 8-96 kHz

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

### Quick Start

1. Download the script `volvo_usb_verifier.py`
2. Install the required library:
   ```bash
   pip install mutagen
   ```
3. Run the script on your USB drive

## Usage

### Windows
```bash
python volvo_usb_verifier.py E:\
```
Replace `E:` with your USB drive letter.

### Linux
```bash
python volvo_usb_verifier.py /media/username/USB_DRIVE
```
Replace the path with your actual mount point.

### macOS
```bash
python volvo_usb_verifier.py /Volumes/USB_DRIVE
```
Replace `USB_DRIVE` with your volume name.

## Understanding the Output

The script will show progress through three phases:
1. Verifying filesystem (FAT32, MBR, cluster size)
2. Verifying file and folder structure (counts, depth, paths)
3. Verifying audio files (formats, encoding, tags)

### Report Sections

- **✓ PASSED CHECKS**: Requirements that are met
- **⚠ WARNINGS**: Non-critical issues that might cause problems
- **✗ ERRORS**: Critical issues that will likely prevent proper operation

### Exit Codes

- `0`: All checks passed
- `1`: Errors found

## Common Issues and Solutions

### Filesystem Errors

**"Filesystem is NTFS, must be FAT32"**
- Solution: Reformat the drive to FAT32
- Windows (≤32GB): Right-click drive → Format → FAT32
- Windows (>32GB): Use [Rufus](https://rufus.ie) or similar tool
- Select MBR partition scheme and 32KB cluster size

**"Partition scheme is GPT, must be MBR"**
- Solution: Reformat using MBR partition scheme
- Use Rufus, GUIFormat, or MiniTool Partition Wizard
- All data will be lost during reformatting

### File Structure Errors

**"Total files exceeds maximum 15,000"**
- Solution: Remove some files or create multiple USB drives

**"Folder has more than 254 files"**
- Solution: Split files across multiple subfolders

**"Max nesting depth exceeds 8"**
- Solution: Flatten your folder structure
- Example: Change `Artist/Album/Track.mp3` to `Artist/Track.mp3`

**"Path too long"**
- Solution: Shorten folder names and file names
- Keep paths under 60 characters total

### Audio File Issues

**"VBR encoding (CBR strongly recommended)"**
- Solution: Re-encode files as CBR using foobar2000, Audacity, or similar
- Recommended: CBR 192 kbps or 256 kbps

**"144 kbps is explicitly not supported"**
- Solution: Re-encode to 192 kbps or higher

**"ID3v2.4 tags"**
- Solution: Use [MP3tag](https://www.mp3tag.de/) to convert to ID3v2.3
- Configure: Tools → Options → Tags → ID3v2.3 with ISO-8859-1

**"Unsupported format FLAC"** (or OGG, WAV)
- Solution: Convert to MP3 (CBR preferred)
- Tools: foobar2000, Audacity, or similar converters

**".m4p file likely has DRM"**
- Solution: Only DRM-free files work
- iTunes purchases before 2009 have DRM
- Apple Music downloads always have DRM

## Recommended Workflow

1. **Format your USB drive properly**
   - 32GB or smaller recommended
   - FAT32 filesystem
   - MBR partition scheme
   - 32KB cluster size

2. **Prepare your audio files**
   - Convert to MP3 (CBR encoding)
   - Use [MP3tag](https://www.mp3tag.de/) to standardize ID3 tags to v2.3
   - Keep folder structure shallow (max 8 levels)
   - Use short, simple file and folder names

3. **Copy files to USB drive**
   - Organize: `Artist/Track.mp3` structure recommended
   - Keep under 15,000 total files
   - Keep under 254 files per folder

4. **Run this verifier script**
   ```bash
   python volvo_usb_verifier.py <drive_path>
   ```

5. **Fix any errors reported**

6. **Test in vehicle**
   - Start with a small subset (20-30 files) to verify
   - If successful, add more files gradually

## Limitations

- Script cannot detect all possible playback issues
- Some filesystem checks require administrator/root privileges
- VBR detection may not catch all problematic encodings
- Album art size is estimated, not precisely measured

## Recommended Tools

- **MP3tag**: ID3 tag standardization ([mp3tag.de](https://www.mp3tag.de/))
- **foobar2000**: Audio format conversion ([foobar2000.org](https://www.foobar2000.org/))
- **Rufus**: USB drive formatting on Windows ([rufus.ie](https://rufus.ie))
- **MediaInfo**: Detailed file analysis ([mediaarea.net](https://mediaarea.net/))
- **FAT Sorter**: Alphabetize files on FAT32 drives

## License

This script is provided as-is for personal use. No warranty is provided.

## References

Based on specifications compiled from:
- Volvo owner forums (SwedeSpeed, VolvOwners)
- 2012 Volvo XC70 owner manual USB specifications
- Real-world testing by Volvo owners
