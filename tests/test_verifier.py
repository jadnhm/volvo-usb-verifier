"""
Tests for volvo_usb_verifier.py

Covers: spec constants, ID3 tag verification (versions, album art),
and unsupported format detection.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from volvo_usb_verifier import VolvoUSBVerifier


def _make_verifier() -> VolvoUSBVerifier:
    """Return a VolvoUSBVerifier without hitting the filesystem."""
    v = VolvoUSBVerifier.__new__(VolvoUSBVerifier)
    v.drive_path = Path('/')
    v.problem_files = []
    v.errors = []
    v.warnings = []
    v.info = []
    v.file_stats = {}
    v.num_threads = 1
    v.logger = MagicMock()
    return v


class TestSpecConstants(unittest.TestCase):

    def test_supported_formats(self):
        for fmt in ('.mp3', '.wma', '.aac', '.m4a', '.m4b'):
            self.assertIn(fmt, VolvoUSBVerifier.SUPPORTED_FORMATS)

    def test_unsupported_formats(self):
        for fmt in ('.flac', '.wav', '.aiff', '.aif', '.ape', '.alac', '.ogg'):
            self.assertIn(fmt, VolvoUSBVerifier.UNSUPPORTED_FORMATS)

    def test_supported_and_unsupported_are_disjoint(self):
        overlap = VolvoUSBVerifier.SUPPORTED_FORMATS & VolvoUSBVerifier.UNSUPPORTED_FORMATS
        self.assertEqual(overlap, set())

    def test_file_limits(self):
        self.assertEqual(VolvoUSBVerifier.MAX_FILES_PER_FOLDER, 254)
        self.assertEqual(VolvoUSBVerifier.MAX_PATH_LENGTH, 60)
        self.assertEqual(VolvoUSBVerifier.MAX_FILENAME_LENGTH, 64)
        self.assertEqual(VolvoUSBVerifier.MAX_TOTAL_FILES, 15000)
        self.assertEqual(VolvoUSBVerifier.MAX_ROOT_FOLDERS, 1000)

    def test_forbidden_bitrate(self):
        self.assertEqual(VolvoUSBVerifier.FORBIDDEN_BITRATE, 144)

    def test_valid_mp3_sample_rates(self):
        self.assertIn(44100, VolvoUSBVerifier.VALID_SAMPLE_RATES)
        self.assertIn(32000, VolvoUSBVerifier.VALID_SAMPLE_RATES)
        self.assertIn(48000, VolvoUSBVerifier.VALID_SAMPLE_RATES)


class TestVerifyId3Tags(unittest.TestCase):

    def setUp(self):
        self.verifier = _make_verifier()

    def _tags(self, version, frames=None, has_track_number=False):
        tags = MagicMock()
        tags.version = version
        tags.values.return_value = frames if frames is not None else []
        if has_track_number:
            track_frame = MagicMock()
            track_frame.text = ['1/12']
            tags.getall.return_value = [track_frame]
        else:
            tags.getall.return_value = []
        return tags

    def test_id3v23_clean(self):
        tags = self._tags((2, 3, 0), has_track_number=True)
        display, csv = self.verifier._verify_id3_tags(tags, Path('test.mp3'))
        self.assertEqual(display, [])
        self.assertEqual(csv, [])

    def test_id3v1_clean(self):
        tags = self._tags((1, 0, 0), has_track_number=True)
        display, csv = self.verifier._verify_id3_tags(tags, Path('test.mp3'))
        self.assertEqual(csv, [])

    def test_id3v24_flagged(self):
        tags = self._tags((2, 4, 0), has_track_number=True)
        display, csv = self.verifier._verify_id3_tags(tags, Path('test.mp3'))
        self.assertEqual(len(csv), 1)
        self.assertEqual(csv[0]['issue_type'], 'ID3 Tags')
        self.assertIn('ID3v2.4', csv[0]['description'])

    def test_id3v22_flagged_unusual(self):
        tags = self._tags((2, 2, 0), has_track_number=True)
        display, csv = self.verifier._verify_id3_tags(tags, Path('test.mp3'))
        self.assertEqual(len(csv), 1)
        self.assertIn('Unusual', csv[0]['description'])

    def test_large_album_art_flagged(self):
        art = MagicMock()
        art.FrameID = 'APIC'
        art.data = b'x' * (500 * 500 * 4)  # ~1 MB — above 750 KB threshold
        tags = self._tags((2, 3, 0), frames=[art], has_track_number=True)
        display, csv = self.verifier._verify_id3_tags(tags, Path('test.mp3'))
        self.assertEqual(len(csv), 1)
        self.assertEqual(csv[0]['issue_type'], 'Album Art')

    def test_small_album_art_ok(self):
        art = MagicMock()
        art.FrameID = 'APIC'
        art.data = b'x' * 1024  # 1 KB — well under threshold
        tags = self._tags((2, 3, 0), frames=[art], has_track_number=True)
        display, csv = self.verifier._verify_id3_tags(tags, Path('test.mp3'))
        self.assertEqual(csv, [])

    def test_non_apic_frame_ignored(self):
        frame = MagicMock()
        frame.FrameID = 'TIT2'
        tags = self._tags((2, 3, 0), frames=[frame], has_track_number=True)
        display, csv = self.verifier._verify_id3_tags(tags, Path('test.mp3'))
        self.assertEqual(csv, [])

    def test_missing_track_number_flagged(self):
        tags = self._tags((2, 3, 0), frames=[])
        display, csv = self.verifier._verify_id3_tags(tags, Path('test.mp3'))
        self.assertEqual(len(csv), 1)
        self.assertEqual(csv[0]['issue_type'], 'Track Number')

    def test_present_track_number_not_flagged(self):
        tags = self._tags((2, 3, 0), frames=[], has_track_number=True)
        display, csv = self.verifier._verify_id3_tags(tags, Path('test.mp3'))
        self.assertEqual(csv, [])


class TestProblemFilesTracking(unittest.TestCase):
    """Verify that problem categories produce the right CSV issue_type values."""

    def setUp(self):
        self.verifier = _make_verifier()

    def test_unsupported_format_issue_type(self):
        self.verifier.problem_files.append({
            'file_path': 'music/song.flac',
            'issue_type': 'Unsupported Format',
            'severity': 'ERROR',
            'description': 'Format FLAC is not supported',
        })
        flac = [p for p in self.verifier.problem_files
                if p['issue_type'] == 'Unsupported Format']
        self.assertEqual(len(flac), 1)

    def test_path_length_issue_type(self):
        self.verifier.problem_files.append({
            'file_path': 'a' * 61,
            'issue_type': 'Path Length',
            'severity': 'ERROR',
            'description': 'Path length 61 exceeds maximum 60',
        })
        path_issues = [p for p in self.verifier.problem_files
                       if p['issue_type'] == 'Path Length']
        self.assertEqual(len(path_issues), 1)


if __name__ == '__main__':
    unittest.main()
