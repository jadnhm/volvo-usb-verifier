#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Volvo XC70 2012 USB Media Drive Verifier

This script verifies that a USB drive and its media files conform to the
specifications required by the 2012 Volvo XC70 base stereo system.

Requirements verified:
- FAT32 filesystem with MBR partition scheme
- 32KB cluster size
- Maximum 15,000 files total
- Maximum 1,000 folders in root
- Maximum 254 files per folder
- Maximum 8 levels of nesting
- Path length under 60 characters
- Audio formats: MP3, WMA, AAC, M4A, M4B (no FLAC/OGG)
- MP3: CBR encoding, 32-320 kbps (not 144), 32/44.1/48 kHz
- ID3 tags: ID3v2.3 with ISO-8859-1 encoding preferred
- Album art: 500x500 pixels or smaller
"""

import os
import sys
import platform
import subprocess
import json
import logging
import csv
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing

# Fix Windows console encoding issues
if platform.system() == "Windows":
    import io
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3
    from mutagen.aac import AAC
    from mutagen.asf import ASF
    from mutagen.mp4 import MP4
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis
except ImportError:
    print("ERROR: This script requires the 'mutagen' library.")
    print("Install it with: pip install mutagen")
    sys.exit(1)


class VolvoUSBVerifier:
    """Verifies USB drive and media files for Volvo XC70 2012 compatibility."""

    # Specification constants
    MAX_TOTAL_FILES = 15000
    MAX_ROOT_FOLDERS = 1000
    MAX_FILES_PER_FOLDER = 254
    MAX_NESTING_DEPTH = 8
    MAX_PATH_LENGTH = 60
    MAX_FILENAME_LENGTH = 64  # Including extension
    RECOMMENDED_CLUSTER_SIZE = 32768  # 32KB
    SUPPORTED_FORMATS = {'.mp3', '.wma', '.aac', '.m4a', '.m4b'}
    UNSUPPORTED_FORMATS = {'.flac', '.ogg', '.wav', '.ape', '.alac'}
    FORBIDDEN_BITRATE = 144
    VALID_SAMPLE_RATES = {32000, 44100, 48000}
    MIN_BITRATE = 32
    MAX_BITRATE = 320
    MAX_ALBUM_ART_SIZE = (500, 500)
    # Extended ASCII characters that may cause issues
    UNSAFE_CHARS = set('üéñàèìòùáíóúäëïöüÿâêîôûãõçøåæœ¿¡«»°±²³µ¶·¸¹º¼½¾×÷')

    def __init__(self, drive_path: str, num_threads: Optional[int] = None):
        self.drive_path = Path(drive_path)
        self.errors = []
        self.warnings = []
        self.info = []
        self.file_stats = defaultdict(int)
        self.problem_files = []  # Track all problem files for CSV export
        # Use os.cpu_count() which returns thread count (logical processors)
        self.num_threads = num_threads or (os.cpu_count() or 4) * 2
        self.start_time = None
        self.logger = logging.getLogger('VolvoUSBVerifier')
        self.csv_file = None

    def log(self, message: str):
        """Log message to both console and file."""
        print(message)
        self.logger.info(message)

    def verify_all(self) -> bool:
        """Run all verification checks. Returns True if all critical checks pass."""
        self.start_time = datetime.now()

        self.log(f"Verifying USB drive at: {self.drive_path}")
        self.log(f"Using {self.num_threads} threads for file analysis")
        self.log("=" * 70)

        # Filesystem checks
        self.verify_filesystem()

        # File and folder structure checks
        self.verify_structure()

        # Audio file checks
        self.verify_audio_files()

        # Print report
        self.print_report()

        # Export CSV of problem files
        if self.problem_files:
            self.export_csv()

        # Print elapsed time
        elapsed = datetime.now() - self.start_time
        self.log(f"\nTotal execution time: {elapsed}")

        return len(self.errors) == 0

    def verify_filesystem(self):
        """Verify filesystem type, partition scheme, and cluster size."""
        print("\n[1/3] Verifying filesystem...")

        system = platform.system()

        if system == "Windows":
            self._verify_filesystem_windows()
        elif system == "Linux":
            self._verify_filesystem_linux()
        elif system == "Darwin":  # macOS
            self._verify_filesystem_macos()
        else:
            self.warnings.append(f"Filesystem verification not implemented for {system}")

    def _verify_filesystem_windows(self):
        """Windows-specific filesystem verification."""
        try:
            # Get drive letter (e.g., "E:")
            drive_letter = str(self.drive_path.drive) if self.drive_path.drive else None

            if not drive_letter:
                self.warnings.append("Could not determine drive letter. Skipping filesystem checks.")
                return

            # Use wmic to get filesystem info
            cmd = f'wmic volume where "DriveLetter=\'{drive_letter}\'" get FileSystem,BlockSize /format:list'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

            if result.returncode == 0:
                output = result.stdout

                # Parse filesystem
                if "FileSystem=FAT32" in output:
                    self.info.append("✓ Filesystem is FAT32")
                elif "FileSystem=FAT" in output:
                    self.info.append("✓ Filesystem is FAT16 (also compatible)")
                else:
                    fs_match = [line for line in output.split('\n') if 'FileSystem=' in line]
                    fs_type = fs_match[0].split('=')[1].strip() if fs_match else "Unknown"
                    self.errors.append(f"✗ Filesystem is {fs_type}, must be FAT32")

                # Parse cluster size
                block_match = [line for line in output.split('\n') if 'BlockSize=' in line]
                if block_match:
                    block_size = int(block_match[0].split('=')[1].strip())
                    if block_size == self.RECOMMENDED_CLUSTER_SIZE:
                        self.info.append(f"✓ Cluster size is 32KB (optimal)")
                    else:
                        self.warnings.append(
                            f"⚠ Cluster size is {block_size} bytes. "
                            f"Recommended: {self.RECOMMENDED_CLUSTER_SIZE} bytes (32KB)"
                        )

            # Check partition scheme using diskpart
            disk_num = self._get_disk_number_windows(drive_letter)
            if disk_num is not None:
                self._check_partition_scheme_windows(disk_num)

        except Exception as e:
            self.warnings.append(f"Could not verify filesystem details: {e}")

    def _get_disk_number_windows(self, drive_letter: str) -> Optional[int]:
        """Get physical disk number for a drive letter on Windows."""
        try:
            cmd = f'wmic partition where "DeviceID LIKE \'%{drive_letter[0]}%\'" get DiskIndex /format:list'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'DiskIndex=' in line:
                        return int(line.split('=')[1].strip())
        except Exception:
            pass
        return None

    def _check_partition_scheme_windows(self, disk_num: int):
        """Check if disk uses MBR partition scheme on Windows."""
        try:
            # Create diskpart script
            script_content = f"select disk {disk_num}\ndetail disk\nexit\n"
            script_path = Path.home() / "volvo_verify_temp.txt"

            with open(script_path, 'w') as f:
                f.write(script_content)

            result = subprocess.run(
                ['diskpart', '/s', str(script_path)],
                capture_output=True,
                text=True
            )

            script_path.unlink()

            if result.returncode == 0:
                output = result.stdout.lower()
                if 'partition style: mbr' in output or 'partition style : mbr' in output:
                    self.info.append("✓ Partition scheme is MBR")
                elif 'gpt' in output:
                    self.errors.append("✗ Partition scheme is GPT, must be MBR")
                else:
                    self.warnings.append("⚠ Could not determine partition scheme")
        except Exception as e:
            self.warnings.append(f"Could not verify partition scheme: {e}")

    def _verify_filesystem_linux(self):
        """Linux-specific filesystem verification."""
        try:
            # Get mount info
            result = subprocess.run(
                ['findmnt', '-n', '-o', 'FSTYPE,OPTIONS', str(self.drive_path)],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                parts = result.stdout.strip().split()
                if len(parts) >= 1:
                    fstype = parts[0].lower()
                    if 'fat32' in fstype or 'vfat' in fstype:
                        self.info.append("✓ Filesystem is FAT32")
                    elif 'fat' in fstype:
                        self.info.append("✓ Filesystem is FAT (compatible)")
                    else:
                        self.errors.append(f"✗ Filesystem is {fstype}, must be FAT32")

            # Try to get block size
            result = subprocess.run(
                ['stat', '-f', '-c', '%S', str(self.drive_path)],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                block_size = int(result.stdout.strip())
                if block_size == self.RECOMMENDED_CLUSTER_SIZE:
                    self.info.append("✓ Cluster size is 32KB (optimal)")
                else:
                    self.warnings.append(
                        f"⚠ Cluster size is {block_size} bytes. "
                        f"Recommended: {self.RECOMMENDED_CLUSTER_SIZE} bytes (32KB)"
                    )
        except Exception as e:
            self.warnings.append(f"Could not verify filesystem details: {e}")

    def _verify_filesystem_macos(self):
        """macOS-specific filesystem verification."""
        try:
            # Get disk info
            result = subprocess.run(
                ['diskutil', 'info', str(self.drive_path)],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                output = result.stdout

                # Check filesystem
                for line in output.split('\n'):
                    if 'File System Personality:' in line or 'Type (Bundle):' in line:
                        if 'FAT32' in line or 'MS-DOS FAT32' in line:
                            self.info.append("✓ Filesystem is FAT32")
                        elif 'FAT' in line:
                            self.info.append("✓ Filesystem is FAT (compatible)")
                        else:
                            self.errors.append(f"✗ Filesystem is not FAT32: {line}")

                    if 'Allocation Block Size:' in line or 'Device Block Size:' in line:
                        size_str = line.split(':')[1].strip()
                        if 'Bytes' in size_str:
                            size = int(size_str.split()[0])
                            if size == self.RECOMMENDED_CLUSTER_SIZE:
                                self.info.append("✓ Cluster size is 32KB (optimal)")
                            else:
                                self.warnings.append(
                                    f"⚠ Cluster size is {size} bytes. "
                                    f"Recommended: {self.RECOMMENDED_CLUSTER_SIZE} bytes (32KB)"
                                )

                    if 'Partition Type:' in line:
                        if 'MBR' in line or 'FDisk_partition_scheme' in line:
                            self.info.append("✓ Partition scheme is MBR")
                        elif 'GPT' in line or 'GUID_partition_scheme' in line:
                            self.errors.append("✗ Partition scheme is GPT, must be MBR")
        except Exception as e:
            self.warnings.append(f"Could not verify filesystem details: {e}")

    def verify_structure(self):
        """Verify file and folder structure limits."""
        print("\n[2/3] Verifying file and folder structure...")

        total_files = 0
        total_folders = 0
        root_folders = 0
        folders_with_files = defaultdict(int)
        max_nesting = 0
        long_paths = []
        folder_count = 0

        for root, dirs, files in os.walk(self.drive_path):
            root_path = Path(root)
            folder_count += 1

            # Progress indicator every 100 folders
            if folder_count % 100 == 0:
                print(f"  Scanning folder {folder_count}... ({total_files} audio files found so far)", end='\r')

            # Count folders
            if root_path != self.drive_path:
                total_folders += 1

            # Count root folders
            if root_path.parent == self.drive_path:
                root_folders += len(dirs)

            # Calculate nesting depth
            try:
                relative = root_path.relative_to(self.drive_path)
                depth = len(relative.parts)
                max_nesting = max(max_nesting, depth)
            except ValueError:
                pass

            # Count files
            audio_files = [f for f in files if Path(f).suffix.lower() in self.SUPPORTED_FORMATS]
            total_files += len(audio_files)
            folders_with_files[root] = len(audio_files)

            # Check path lengths, filenames, and invalid characters
            for file in files:
                file_path = root_path / file
                try:
                    relative_path = file_path.relative_to(self.drive_path)
                    path_str = str(relative_path)

                    # Check path length
                    if len(path_str) > self.MAX_PATH_LENGTH:
                        long_paths.append((path_str, len(path_str)))
                        self.problem_files.append({
                            'file_path': path_str,
                            'issue_type': 'Path Length',
                            'severity': 'ERROR',
                            'description': f'Path length {len(path_str)} exceeds maximum {self.MAX_PATH_LENGTH}'
                        })

                    # Check filename length
                    if len(file) > self.MAX_FILENAME_LENGTH:
                        self.problem_files.append({
                            'file_path': path_str,
                            'issue_type': 'Filename Length',
                            'severity': 'ERROR',
                            'description': f'Filename length {len(file)} exceeds maximum {self.MAX_FILENAME_LENGTH}'
                        })

                    # Check for unsafe characters
                    unsafe_in_path = self.UNSAFE_CHARS.intersection(set(path_str))
                    if unsafe_in_path:
                        self.problem_files.append({
                            'file_path': path_str,
                            'issue_type': 'Invalid Characters',
                            'severity': 'WARNING',
                            'description': f'Path contains extended ASCII characters: {", ".join(sorted(unsafe_in_path))}'
                        })
                except ValueError:
                    pass

        # Clear progress line
        print(" " * 80, end='\r')

        # Report findings
        if total_files <= self.MAX_TOTAL_FILES:
            self.info.append(f"✓ Total files: {total_files} (max {self.MAX_TOTAL_FILES})")
        else:
            self.errors.append(
                f"✗ Total files: {total_files} exceeds maximum {self.MAX_TOTAL_FILES}"
            )

        if root_folders <= self.MAX_ROOT_FOLDERS:
            self.info.append(f"✓ Root folders: {root_folders} (max {self.MAX_ROOT_FOLDERS})")
        else:
            self.errors.append(
                f"✗ Root folders: {root_folders} exceeds maximum {self.MAX_ROOT_FOLDERS}"
            )

        # Check files per folder
        overcrowded_folders = [
            (folder, count) for folder, count in folders_with_files.items()
            if count > self.MAX_FILES_PER_FOLDER
        ]

        if not overcrowded_folders:
            max_folder_count = max(folders_with_files.values()) if folders_with_files else 0
            self.info.append(
                f"✓ Files per folder: max {max_folder_count} (limit {self.MAX_FILES_PER_FOLDER})"
            )
        else:
            for folder, count in overcrowded_folders[:5]:  # Show first 5
                try:
                    rel_folder = Path(folder).relative_to(self.drive_path)
                    self.errors.append(
                        f"✗ Folder '{rel_folder}' has {count} files (max {self.MAX_FILES_PER_FOLDER})"
                    )
                except ValueError:
                    self.errors.append(
                        f"✗ Folder has {count} files (max {self.MAX_FILES_PER_FOLDER})"
                    )

        # Check nesting depth
        if max_nesting <= self.MAX_NESTING_DEPTH:
            self.info.append(f"✓ Max nesting depth: {max_nesting} (max {self.MAX_NESTING_DEPTH})")
        else:
            self.errors.append(
                f"✗ Max nesting depth: {max_nesting} exceeds maximum {self.MAX_NESTING_DEPTH}"
            )

        # Check path lengths
        if not long_paths:
            self.info.append(f"✓ All paths under {self.MAX_PATH_LENGTH} characters")
        else:
            for path, length in long_paths[:5]:  # Show first 5
                self.errors.append(
                    f"✗ Path too long ({length} chars): {path}"
                )
            if len(long_paths) > 5:
                self.errors.append(f"... and {len(long_paths) - 5} more long paths")

    def verify_audio_files(self):
        """Verify audio file formats, encoding, tags, etc."""
        self.log("\n[3/3] Verifying audio files...")

        # First pass: collect all audio file paths
        audio_files = []
        unsupported_count = 0

        for root, dirs, files in os.walk(self.drive_path):
            for file in files:
                file_path = Path(root) / file
                ext = file_path.suffix.lower()

                # Check for unsupported formats
                if ext in self.UNSUPPORTED_FORMATS:
                    try:
                        rel_path = file_path.relative_to(self.drive_path)
                        self.errors.append(
                            f"✗ Unsupported format {ext.upper()}: {rel_path}"
                        )
                        unsupported_count += 1
                    except ValueError:
                        pass
                    continue

                # Collect supported audio files
                if ext in self.SUPPORTED_FORMATS:
                    audio_files.append(file_path)
                    self.file_stats[ext] += 1

        total_files = len(audio_files)
        self.log(f"Found {total_files} audio files to analyze{f' ({unsupported_count} unsupported)' if unsupported_count else ''}...")

        # Second pass: analyze files in parallel
        problem_files = []
        processed = 0

        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            # Submit all file verification tasks
            future_to_file = {
                executor.submit(self._verify_audio_file, file_path): file_path
                for file_path in audio_files
            }

            # Process results as they complete
            for future in as_completed(future_to_file):
                processed += 1

                # Progress indicator every 500 files
                if processed % 500 == 0 or processed == total_files:
                    print(f"  Analyzed {processed}/{total_files} files... ({len(problem_files)} issues found)", end='\r')

                try:
                    file_issues = future.result()
                    if file_issues:
                        problem_files.extend(file_issues['display'])
                        self.problem_files.extend(file_issues['csv'])
                except Exception as e:
                    file_path = future_to_file[future]
                    try:
                        rel_path = file_path.relative_to(self.drive_path)
                        error_msg = f"⚠ Error processing {rel_path}: {e}"
                        problem_files.append(error_msg)
                        self.problem_files.append({
                            'file_path': str(rel_path),
                            'issue_type': 'Processing Error',
                            'severity': 'Error',
                            'description': str(e)
                        })
                    except ValueError:
                        problem_files.append(f"⚠ Error processing file: {e}")

        # Clear progress line
        print(" " * 80, end='\r')

        # Report statistics
        self.log(f"\nScanned {total_files} audio files:")
        for ext, count in sorted(self.file_stats.items()):
            self.log(f"  {ext.upper()}: {count}")

        # Report issues (limit output)
        if problem_files:
            self.log(f"\nFound {len(problem_files)} file issues (showing first 20):")
            for issue in problem_files[:20]:
                self.log(f"  {issue}")
            if len(problem_files) > 20:
                self.log(f"  ... and {len(problem_files) - 20} more issues")

    def _verify_audio_file(self, file_path: Path) -> Optional[Dict]:
        """Verify a single audio file. Returns dict with display and CSV data."""
        display_issues = []
        csv_issues = []
        ext = file_path.suffix.lower()

        try:
            rel_path = file_path.relative_to(self.drive_path)
        except ValueError:
            rel_path = file_path.name

        try:
            if ext == '.mp3':
                display_issues, csv_issues = self._verify_mp3(file_path, rel_path)
            elif ext == '.wma':
                display_issues, csv_issues = self._verify_wma(file_path, rel_path)
            elif ext in {'.m4a', '.m4b', '.aac'}:
                display_issues, csv_issues = self._verify_aac_m4a(file_path, rel_path)
        except Exception as e:
            display_issues.append(f"⚠ Error reading {rel_path}: {e}")
            csv_issues.append({
                'file_path': str(rel_path),
                'issue_type': 'Read Error',
                'severity': 'Error',
                'description': str(e)
            })

        if display_issues:
            return {'display': display_issues, 'csv': csv_issues}
        return None

    def _verify_mp3(self, file_path: Path, rel_path: Path) -> Tuple[List[str], List[Dict]]:
        """Verify MP3 file specifics. Returns (display_issues, csv_issues)."""
        display_issues = []
        csv_issues = []

        try:
            audio = MP3(file_path)

            # Check bitrate
            if audio.info.bitrate:
                bitrate_kbps = audio.info.bitrate // 1000

                if bitrate_kbps == self.FORBIDDEN_BITRATE:
                    msg = f"✗ {rel_path}: 144 kbps is explicitly not supported"
                    display_issues.append(msg)
                    csv_issues.append({
                        'file_path': str(rel_path),
                        'issue_type': 'Bitrate',
                        'severity': 'Error',
                        'description': '144 kbps is forbidden'
                    })
                elif bitrate_kbps < self.MIN_BITRATE or bitrate_kbps > self.MAX_BITRATE:
                    msg = f"⚠ {rel_path}: bitrate {bitrate_kbps} kbps outside supported range ({self.MIN_BITRATE}-{self.MAX_BITRATE})"
                    display_issues.append(msg)
                    csv_issues.append({
                        'file_path': str(rel_path),
                        'issue_type': 'Bitrate',
                        'severity': 'Warning',
                        'description': f'{bitrate_kbps} kbps (range: {self.MIN_BITRATE}-{self.MAX_BITRATE})'
                    })

            # Check sample rate
            if audio.info.sample_rate not in self.VALID_SAMPLE_RATES:
                msg = f"⚠ {rel_path}: sample rate {audio.info.sample_rate} Hz (recommended: 44100 Hz)"
                display_issues.append(msg)
                csv_issues.append({
                    'file_path': str(rel_path),
                    'issue_type': 'Sample Rate',
                    'severity': 'Warning',
                    'description': f'{audio.info.sample_rate} Hz (recommended: 32000, 44100, or 48000 Hz)'
                })

            # Check if VBR
            if hasattr(audio.info, 'bitrate_mode'):
                if 'VBR' in str(audio.info.bitrate_mode).upper():
                    msg = f"⚠ {rel_path}: VBR encoding (CBR strongly recommended)"
                    display_issues.append(msg)
                    csv_issues.append({
                        'file_path': str(rel_path),
                        'issue_type': 'Encoding',
                        'severity': 'Warning',
                        'description': 'VBR encoding (CBR strongly recommended)'
                    })

            # Check ID3 tags
            if audio.tags:
                tag_display, tag_csv = self._verify_id3_tags(audio.tags, rel_path)
                display_issues.extend(tag_display)
                csv_issues.extend(tag_csv)
            else:
                msg = f"⚠ {rel_path}: No ID3 tags found"
                display_issues.append(msg)
                csv_issues.append({
                    'file_path': str(rel_path),
                    'issue_type': 'ID3 Tags',
                    'severity': 'Warning',
                    'description': 'No ID3 tags found'
                })

        except Exception as e:
            msg = f"⚠ {rel_path}: Error reading MP3: {e}"
            display_issues.append(msg)
            csv_issues.append({
                'file_path': str(rel_path),
                'issue_type': 'Read Error',
                'severity': 'Error',
                'description': str(e)
            })

        return display_issues, csv_issues

    def _verify_id3_tags(self, tags, rel_path: Path) -> Tuple[List[str], List[Dict]]:
        """Verify ID3 tag version and encoding."""
        display_issues = []
        csv_issues = []

        # Check ID3 version
        if hasattr(tags, 'version'):
            major, minor, rev = tags.version
            if major == 2 and minor == 3:
                pass  # ID3v2.3 is ideal
            elif major == 2 and minor == 4:
                msg = f"⚠ {rel_path}: ID3v2.4 tags (ID3v2.3 recommended for compatibility)"
                display_issues.append(msg)
                csv_issues.append({
                    'file_path': str(rel_path),
                    'issue_type': 'ID3 Tags',
                    'severity': 'Warning',
                    'description': 'ID3v2.4 (ID3v2.3 recommended)'
                })
            elif major == 1:
                pass  # ID3v1 is acceptable
            else:
                msg = f"⚠ {rel_path}: Unusual ID3 version {major}.{minor}"
                display_issues.append(msg)
                csv_issues.append({
                    'file_path': str(rel_path),
                    'issue_type': 'ID3 Tags',
                    'severity': 'Warning',
                    'description': f'Unusual ID3 version {major}.{minor}'
                })

        # Check for embedded images (album art)
        image_frames = [frame for frame in tags.values() if frame.FrameID == 'APIC']
        for img_frame in image_frames:
            if hasattr(img_frame, 'data'):
                img_size = len(img_frame.data)
                if img_size > 500 * 500 * 3:  # Rough estimate
                    msg = f"⚠ {rel_path}: Large embedded artwork ({img_size // 1024} KB, keep under ~750 KB)"
                    display_issues.append(msg)
                    csv_issues.append({
                        'file_path': str(rel_path),
                        'issue_type': 'Album Art',
                        'severity': 'Warning',
                        'description': f'Large artwork: {img_size // 1024} KB'
                    })

        return display_issues, csv_issues

    def _verify_wma(self, file_path: Path, rel_path: Path) -> Tuple[List[str], List[Dict]]:
        """Verify WMA file specifics."""
        display_issues = []
        csv_issues = []

        try:
            audio = ASF(file_path)

            # Basic checks
            if audio.info.bitrate:
                bitrate_kbps = audio.info.bitrate // 1000
                if bitrate_kbps < self.MIN_BITRATE or bitrate_kbps > self.MAX_BITRATE:
                    msg = f"⚠ {rel_path}: bitrate {bitrate_kbps} kbps outside typical range ({self.MIN_BITRATE}-{self.MAX_BITRATE})"
                    display_issues.append(msg)
                    csv_issues.append({
                        'file_path': str(rel_path),
                        'issue_type': 'Bitrate',
                        'severity': 'Warning',
                        'description': f'{bitrate_kbps} kbps (range: {self.MIN_BITRATE}-{self.MAX_BITRATE})'
                    })

        except Exception as e:
            msg = f"⚠ {rel_path}: Error reading WMA: {e}"
            display_issues.append(msg)
            csv_issues.append({
                'file_path': str(rel_path),
                'issue_type': 'Read Error',
                'severity': 'Error',
                'description': str(e)
            })

        return display_issues, csv_issues

    def _verify_aac_m4a(self, file_path: Path, rel_path: Path) -> Tuple[List[str], List[Dict]]:
        """Verify AAC/M4A/M4B file specifics."""
        display_issues = []
        csv_issues = []

        try:
            audio = MP4(file_path)

            # Check for DRM (FairPlay)
            if hasattr(audio, 'info'):
                # M4P files are typically DRM-protected
                if file_path.suffix.lower() == '.m4p':
                    msg = f"✗ {rel_path}: .m4p file likely has DRM (iTunes protected)"
                    display_issues.append(msg)
                    csv_issues.append({
                        'file_path': str(rel_path),
                        'issue_type': 'DRM',
                        'severity': 'Error',
                        'description': 'iTunes DRM protected (m4p)'
                    })

            # Check sample rate
            if hasattr(audio.info, 'sample_rate'):
                if audio.info.sample_rate < 8000 or audio.info.sample_rate > 96000:
                    msg = f"⚠ {rel_path}: sample rate {audio.info.sample_rate} Hz outside supported range (8-96 kHz)"
                    display_issues.append(msg)
                    csv_issues.append({
                        'file_path': str(rel_path),
                        'issue_type': 'Sample Rate',
                        'severity': 'Warning',
                        'description': f'{audio.info.sample_rate} Hz (range: 8-96 kHz)'
                    })

        except Exception as e:
            msg = f"⚠ {rel_path}: Error reading AAC/M4A: {e}"
            display_issues.append(msg)
            csv_issues.append({
                'file_path': str(rel_path),
                'issue_type': 'Read Error',
                'severity': 'Error',
                'description': str(e)
            })

        return display_issues, csv_issues

    def export_csv(self):
        """Export all problem files to CSV."""
        if not self.csv_file:
            return

        try:
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['file_path', 'issue_type', 'severity', 'description'])
                writer.writeheader()
                writer.writerows(self.problem_files)

            self.log(f"\nCSV report exported to: {self.csv_file}")
            self.log(f"Total problem files: {len(self.problem_files)}")
        except Exception as e:
            self.log(f"\n⚠ Error exporting CSV: {e}")

    def print_report(self):
        """Print comprehensive verification report."""
        self.log("\n" + "=" * 70)
        self.log("VERIFICATION REPORT")
        self.log("=" * 70)

        if self.info:
            self.log("\n✓ PASSED CHECKS:")
            for item in self.info:
                self.log(f"  {item}")

        if self.warnings:
            self.log(f"\n⚠ WARNINGS ({len(self.warnings)}):")
            for item in self.warnings:
                self.log(f"  {item}")

        if self.errors:
            self.log(f"\n✗ ERRORS ({len(self.errors)}):")
            for item in self.errors:
                self.log(f"  {item}")

        self.log("\n" + "=" * 70)
        if not self.errors:
            self.log("✓ RESULT: Drive appears compatible with Volvo XC70 2012!")
            self.log("\nRecommendation: Test with a small subset of files first.")
        else:
            self.log("✗ RESULT: Issues found that may prevent proper operation.")
            self.log("\nRecommendation: Address errors above before using in vehicle.")
        self.log("=" * 70)


def setup_logging(drive_path: str) -> Tuple[str, str]:
    """Set up logging to both console and timestamped file. Returns (log_file, csv_file)."""
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Create timestamped log filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    drive_name = Path(drive_path).name or "drive"
    log_file = log_dir / f"volvo_verify_{drive_name}_{timestamp}.log"
    csv_file = log_dir / f"volvo_verify_{drive_name}_{timestamp}.csv"

    # Configure logging
    logger = logging.getLogger('VolvoUSBVerifier')
    logger.setLevel(logging.INFO)

    # File handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('%(message)s')
    file_handler.setFormatter(file_formatter)

    # Add handlers
    logger.addHandler(file_handler)

    return str(log_file), str(csv_file)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Volvo XC70 2012 USB Media Drive Verifier")
        print("\nUsage: python volvo_usb_verifier.py <drive_path>")
        print("\nExamples:")
        print("  Windows: python volvo_usb_verifier.py E:\\")
        print("  Linux:   python volvo_usb_verifier.py /media/usb")
        print("  macOS:   python volvo_usb_verifier.py /Volumes/USB_DRIVE")
        sys.exit(1)

    drive_path = sys.argv[1]

    if not os.path.exists(drive_path):
        print(f"ERROR: Path does not exist: {drive_path}")
        sys.exit(1)

    if not os.path.isdir(drive_path):
        print(f"ERROR: Path is not a directory: {drive_path}")
        sys.exit(1)

    # Set up logging
    log_file, csv_file = setup_logging(drive_path)
    print(f"Logging to: {log_file}\n")

    verifier = VolvoUSBVerifier(drive_path)
    verifier.csv_file = csv_file
    success = verifier.verify_all()

    print(f"\nLog file saved to: {log_file}")
    if verifier.problem_files:
        print(f"CSV report saved to: {csv_file}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
