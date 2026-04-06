# Volvo XC70 2012 USB Media Toolchain

A Python toolchain for preparing USB drives with media files compatible with the 2012 Volvo XC70 base stereo.

See [README.md](../README.md) for full usage docs and [DEVELOPMENT.md](../DEVELOPMENT.md) for implementation details.

## Project Structure

Two independent toolsets live in this repo:

### 1. Volvo USB Preparation Pipeline (main toolset)

Three scripts that work in a strict pipeline order:

1. **`volvo_usb_verifier.py`** — Scans a USB drive, outputs a timestamped `.log` + `.csv` to `logs/`
2. **`volvo_path_fixer.py`** — Renames files/folders to fix filename length and invalid characters. **Run this before the ID3 fixer** — renaming invalidates CSV paths.
3. **`volvo_usb_fixer.py`** — Fixes ID3 tags losslessly (version, missing tags, oversized art). Takes the CSV from the verifier as input.

All three support dry-run mode by default; pass `--apply` to make changes.

### 2. Audiobook Renaming Toolset (AI-assisted)

- **`rename_audiobooks_batch.py`** — Preferred. Groups files by book, makes one Claude API call per book (93% fewer calls). Uses the `v7_refined` prompt.
- **`rename_audiobooks.py`** — Per-file fallback for unusual edge cases.
- **`test_path_shortening.py`** — Test suite validating prompt accuracy.
- **`sample_rename_preview.py`** — Samples one file per directory for a quick preview.

The `VOLVO/` folder is a working/staging area; the tested scripts live at the repo root.

## Key Constraints (Volvo Stereo)

- Filesystem: **FAT32, MBR partition, 32KB clusters** (not NTFS/exFAT, not GPT)
- Max **15,000 total files**, **1,000 root folders**, **254 files/folder**, **8 nesting levels**
- **Max path: 60 chars**, **max filename: 64 chars**
- No extended ASCII in filenames (é, ñ, ü, etc.)
- Supported formats: MP3, WMA, AAC/M4A (FLAC/OGG/WAV unsupported)
- MP3: CBR preferred (VBR causes issues), 32–320 kbps, **144 kbps forbidden**
- Sample rate: 32/44.1/48 kHz for MP3
- ID3 tags: **ID3v2.3 + ISO-8859-1** (ID3v2.4 is problematic); save with both ID3v1 and ID3v2.3

## What Can and Cannot Be Auto-Fixed

| Issue | Auto-fixable? | Tool |
|---|---|---|
| ID3 tag version / missing tags | ✅ Lossless | `volvo_usb_fixer.py` |
| Oversized album art | ✅ Lossless | `volvo_usb_fixer.py` |
| Long filenames / invalid chars | ✅ Rename | `volvo_path_fixer.py` |
| VBR → CBR | ❌ Requires re-encode | foobar2000 manually |
| Sample rate / bitrate issues | ❌ Requires re-encode | foobar2000 manually |
| Path length (folder depth) | ❌ Manual rename | — |
| File count > 15K | ❌ Split drives | — |
| FLAC files | ❌ Convert or delete | — |

## Dependencies

```bash
pip install mutagen         # Required for all Volvo USB scripts
# Claude CLI required for audiobook renaming tools
```
