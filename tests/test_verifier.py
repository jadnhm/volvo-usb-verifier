"""
Tests for volvo_usb_verifier.py

Covers: spec constants, ID3 tag verification (versions, album art),
and unsupported format detection.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import lib.volvo_usb_verifier as verifier_module
from lib.volvo_usb_verifier import VolvoUSBVerifier


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


class TestVerifyMp3(unittest.TestCase):

    def setUp(self):
        self.verifier = _make_verifier()

    @patch('lib.volvo_usb_verifier.MP3')
    def test_forbidden_bitrate_flagged_as_error(self, mock_mp3):
        audio = MagicMock()
        audio.info.bitrate = 144000
        audio.info.sample_rate = 44100
        audio.info.bitrate_mode = 'CBR'
        audio.tags = MagicMock()
        audio.tags.values.return_value = []
        audio.tags.getall.return_value = [MagicMock(text=['1/12'])]
        mock_mp3.return_value = audio

        _display, csv = self.verifier._verify_mp3(Path('test.mp3'), Path('test.mp3'))

        self.assertEqual(csv[0]['issue_type'], 'Bitrate')
        self.assertEqual(csv[0]['severity'], 'Error')

    @patch('lib.volvo_usb_verifier.MP3')
    def test_invalid_sample_rate_flagged(self, mock_mp3):
        audio = MagicMock()
        audio.info.bitrate = 192000
        audio.info.sample_rate = 22050
        audio.info.bitrate_mode = 'CBR'
        audio.tags = MagicMock()
        audio.tags.values.return_value = []
        audio.tags.getall.return_value = [MagicMock(text=['1/12'])]
        mock_mp3.return_value = audio

        _display, csv = self.verifier._verify_mp3(Path('test.mp3'), Path('test.mp3'))

        issue_types = [issue['issue_type'] for issue in csv]
        self.assertIn('Sample Rate', issue_types)

    @patch('lib.volvo_usb_verifier.MP3')
    def test_vbr_flagged(self, mock_mp3):
        audio = MagicMock()
        audio.info.bitrate = 192000
        audio.info.sample_rate = 44100
        audio.info.bitrate_mode = 'VBR'
        audio.tags = MagicMock()
        audio.tags.values.return_value = []
        audio.tags.getall.return_value = [MagicMock(text=['1/12'])]
        mock_mp3.return_value = audio

        _display, csv = self.verifier._verify_mp3(Path('test.mp3'), Path('test.mp3'))

        self.assertTrue(any(issue['issue_type'] == 'Encoding' for issue in csv))

    @patch('lib.volvo_usb_verifier.MP3')
    def test_missing_tags_flagged(self, mock_mp3):
        audio = MagicMock()
        audio.info.bitrate = 192000
        audio.info.sample_rate = 44100
        audio.info.bitrate_mode = 'CBR'
        audio.tags = None
        mock_mp3.return_value = audio

        _display, csv = self.verifier._verify_mp3(Path('test.mp3'), Path('test.mp3'))

        self.assertTrue(any(issue['issue_type'] == 'ID3 Tags' for issue in csv))


class TestVerifyWmaAndAac(unittest.TestCase):

    def setUp(self):
        self.verifier = _make_verifier()

    @patch('lib.volvo_usb_verifier.ASF')
    def test_wma_out_of_range_bitrate_flagged(self, mock_asf):
        audio = MagicMock()
        audio.info.bitrate = 500000
        mock_asf.return_value = audio

        _display, csv = self.verifier._verify_wma(Path('test.wma'), Path('test.wma'))

        self.assertEqual(len(csv), 1)
        self.assertEqual(csv[0]['issue_type'], 'Bitrate')

    @patch('lib.volvo_usb_verifier.MP4')
    def test_aac_large_art_and_missing_track_flagged(self, mock_mp4):
        audio = MagicMock()
        audio.info.sample_rate = 44100
        audio.tags = {'covr': [b'x' * (500 * 500 * 4)], 'trkn': []}
        mock_mp4.return_value = audio

        _display, csv = self.verifier._verify_aac_m4a(Path('test.m4a'), Path('test.m4a'))

        issue_types = [issue['issue_type'] for issue in csv]
        self.assertIn('Album Art', issue_types)
        self.assertIn('Track Number', issue_types)

    @patch('lib.volvo_usb_verifier.MP4')
    def test_aac_out_of_range_sample_rate_flagged(self, mock_mp4):
        audio = MagicMock()
        audio.info.sample_rate = 192000
        audio.tags = {'trkn': [(1, 10)]}
        mock_mp4.return_value = audio

        _display, csv = self.verifier._verify_aac_m4a(Path('test.m4a'), Path('test.m4a'))

        self.assertTrue(any(issue['issue_type'] == 'Sample Rate' for issue in csv))


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


class TestVerifyAllCsvBehavior(unittest.TestCase):

    def test_verify_all_exports_csv_even_when_drive_is_clean(self):
        verifier = _make_verifier()
        verifier.csv_file = 'dummy.csv'

        with patch.object(verifier, 'verify_filesystem'), \
             patch.object(verifier, 'verify_structure'), \
             patch.object(verifier, 'verify_audio_files'), \
             patch.object(verifier, 'print_report'), \
             patch.object(verifier, 'export_csv') as mock_export:
            success = verifier.verify_all()

        self.assertTrue(success)
        mock_export.assert_called_once_with()

    def test_export_csv_writes_header_for_clean_run(self):
        verifier = _make_verifier()

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / 'verify.csv'
            verifier.csv_file = str(csv_path)
            verifier.export_csv()

            content = csv_path.read_text(encoding='utf-8').splitlines()
            self.assertEqual(content[0], 'file_path,issue_type,severity,description')
            self.assertEqual(len(content), 1)


class TestVerifierCliBehavior(unittest.TestCase):

    @patch('lib.volvo_usb_verifier.VolvoUSBVerifier.verify_all', side_effect=RuntimeError('boom'))
    @patch('lib.volvo_usb_verifier.setup_logging', return_value=('logs/test.log', 'logs/test.csv'))
    def test_main_uses_distinct_fatal_exit_code_on_unexpected_error(self, _mock_setup, _mock_verify_all):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys, 'argv', ['volvo_usb_verifier.py', tmp]):
                with self.assertRaises(SystemExit) as ctx:
                    verifier_module.main()

        self.assertEqual(ctx.exception.code, verifier_module.EXIT_FATAL)


class TestWindowsFilesystemHelpers(unittest.TestCase):

    @patch('lib.volvo_usb_verifier.subprocess.run')
    def test_verify_filesystem_windows_calls_wmic_without_shell(self, mock_run):
        verifier = _make_verifier()
        verifier.drive_path = Path('E:/')
        mock_run.return_value = MagicMock(returncode=0, stdout='FileSystem=FAT32\nBlockSize=32768\n')

        with patch.object(verifier, '_get_disk_number_windows', return_value=None):
            verifier._verify_filesystem_windows()

        self.assertFalse(mock_run.call_args.kwargs.get('shell', False))
        self.assertEqual(mock_run.call_args.args[0][:3], ['wmic', 'volume', 'where'])

    @patch('lib.volvo_usb_verifier.subprocess.run')
    def test_get_disk_number_windows_calls_wmic_without_shell(self, mock_run):
        verifier = _make_verifier()
        mock_run.return_value = MagicMock(returncode=0, stdout='DiskIndex=4\n')

        disk_num = verifier._get_disk_number_windows('E:')

        self.assertEqual(disk_num, 4)
        self.assertFalse(mock_run.call_args.kwargs.get('shell', False))
        self.assertEqual(mock_run.call_args.args[0][:3], ['wmic', 'partition', 'where'])


class TestVerifyStructure(unittest.TestCase):

    def test_root_folder_count_only_counts_immediate_children(self):
        verifier = _make_verifier()

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'ArtistA' / 'Album').mkdir(parents=True)
            (base / 'ArtistB').mkdir()
            (base / 'ArtistA' / 'Album' / 'track.mp3').write_bytes(b'')

            verifier.drive_path = base
            verifier.file_stats = {}
            verifier.verify_structure()

            self.assertIn('✓ Root folders: 2 (max 1000)', verifier.info)


if __name__ == '__main__':
    unittest.main()
