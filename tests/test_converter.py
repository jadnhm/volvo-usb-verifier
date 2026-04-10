"""
Tests for volvo_converter.py

Covers: safe_output_path, find_lossless_files, is_alac, and resume-skip logic.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.volvo_converter import (
    safe_output_path,
    find_lossless_files,
    is_alac,
    LOSSLESS_EXTENSIONS,
    TARGET_EXTENSION,
    validate_converted_output,
)


class TestSafeOutputPath(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_flac_becomes_m4a(self):
        result = safe_output_path(self.base / 'song.flac')
        self.assertEqual(result.suffix, TARGET_EXTENSION)
        self.assertEqual(result.stem, 'song')

    def test_wav_becomes_m4a(self):
        result = safe_output_path(self.base / 'track.wav')
        self.assertEqual(result.suffix, TARGET_EXTENSION)

    def test_no_collision_when_m4a_already_exists(self):
        (self.base / 'song.m4a').write_bytes(b'existing')
        result = safe_output_path(self.base / 'song.flac')
        self.assertNotEqual(result.name, 'song.m4a')
        self.assertEqual(result.suffix, TARGET_EXTENSION)

    def test_same_m4a_input_no_collision(self):
        # ALAC file that's already in .m4a container — output == input
        m4a = self.base / 'song.m4a'
        result = safe_output_path(m4a)
        self.assertEqual(result, m4a)


class TestFindLosslessFiles(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_flac(self):
        (self.base / 'song.flac').write_bytes(b'')
        results = find_lossless_files(self.base)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].suffix, '.flac')

    def test_finds_wav(self):
        (self.base / 'beat.wav').write_bytes(b'')
        self.assertEqual(len(find_lossless_files(self.base)), 1)

    def test_mp3_not_included(self):
        (self.base / 'track.mp3').write_bytes(b'')
        self.assertEqual(find_lossless_files(self.base), [])

    def test_all_lossless_extensions_found(self):
        for ext in LOSSLESS_EXTENSIONS:
            (self.base / f'test{ext}').write_bytes(b'')
        results = find_lossless_files(self.base)
        found = {f.suffix.lower() for f in results}
        for ext in LOSSLESS_EXTENSIONS:
            self.assertIn(ext, found, f"Extension {ext} not found")

    def test_nested_files_found(self):
        subdir = self.base / 'artist' / 'album'
        subdir.mkdir(parents=True)
        (subdir / 'track.flac').write_bytes(b'')
        results = find_lossless_files(self.base)
        self.assertEqual(len(results), 1)

    def test_empty_directory(self):
        self.assertEqual(find_lossless_files(self.base), [])

    def test_mixed_directory(self):
        (self.base / 'keep.flac').write_bytes(b'')
        (self.base / 'keep.wav').write_bytes(b'')
        (self.base / 'skip.mp3').write_bytes(b'')
        (self.base / 'skip.m4a').write_bytes(b'')  # not ALAC so skipped
        results = find_lossless_files(self.base)
        exts = {f.suffix for f in results}
        self.assertIn('.flac', exts)
        self.assertIn('.wav', exts)
        self.assertNotIn('.mp3', exts)


class TestIsAlac(unittest.TestCase):

    def test_returns_false_when_mutagen_unavailable(self):
        with patch('lib.volvo_converter._MUTAGEN_AVAILABLE', False):
            self.assertFalse(is_alac(Path('fake.m4a')))

    def test_returns_false_on_non_m4a_bytes(self):
        with tempfile.NamedTemporaryFile(suffix='.m4a', delete=False) as f:
            f.write(b'this is not a real m4a file')
            tmp = Path(f.name)
        try:
            self.assertFalse(is_alac(tmp))
        finally:
            tmp.unlink()

    def test_returns_false_on_missing_file(self):
        self.assertFalse(is_alac(Path('/nonexistent/path/fake.m4a')))


class TestResumeSkip(unittest.TestCase):
    """Resume mode should skip files whose output .m4a already exists."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_resume_skips_already_converted(self):
        from lib.volvo_converter import VolvoConverter, setup_logging
        import logging

        flac = self.base / 'song.flac'
        flac.write_bytes(b'')
        # Simulate already-converted output existing
        (self.base / 'song.m4a').write_bytes(b'output')

        logs_dir = self.base / 'artifacts'
        log_file, manifest_file = setup_logging(logs_dir=str(logs_dir))
        converter = VolvoConverter(
            str(self.base),
            dry_run=False,
            resume=True,
            manifest_file=manifest_file,
        )
        # Provide a dummy ffmpeg path — resume should skip before calling ffmpeg
        converter.convert_all(ffmpeg_path='ffmpeg')

        skipped = [r for r in converter.manifest_rows
                   if r['status'] == 'skipped_already_converted']
        self.assertEqual(len(skipped), 1, "Expected file to be skipped in resume mode")
        self.assertEqual(Path(log_file).parent, logs_dir)
        self.assertEqual(Path(manifest_file).parent, logs_dir)

        logger = logging.getLogger('VolvoConverter')
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

        # Original .flac should still exist (we didn't convert)
        self.assertTrue(flac.exists())


class TestOutputValidation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_output_is_invalid(self):
        ok, message = validate_converted_output(self.base / 'missing.m4a')
        self.assertFalse(ok)
        self.assertIn('not created', message)

    def test_zero_byte_output_is_invalid(self):
        output = self.base / 'out.m4a'
        output.write_bytes(b'')
        ok, message = validate_converted_output(output)
        self.assertFalse(ok)
        self.assertIn('zero-byte', message)


class TestLiveConversionSafety(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch('lib.volvo_converter.validate_converted_output', return_value=(True, 'output file verified'))
    @patch('lib.volvo_converter.run_ffmpeg', return_value=(True, 'Converted → song.m4a'))
    @patch('lib.volvo_converter.find_lossless_files')
    def test_live_conversion_deletes_original_only_after_verified_output(
        self,
        mock_find_lossless_files,
        _mock_run_ffmpeg,
        _mock_validate_output,
    ):
        from lib.volvo_converter import VolvoConverter

        flac = self.base / 'song.flac'
        flac.write_bytes(b'lossless')
        output = self.base / 'song.m4a'
        output.write_bytes(b'converted')
        mock_find_lossless_files.return_value = [flac]

        converter = VolvoConverter(str(self.base), dry_run=False, manifest_file=None)
        converter.convert_all(ffmpeg_path='ffmpeg')

        self.assertFalse(flac.exists())
        self.assertTrue(output.exists())
        self.assertEqual(converter.manifest_rows[0]['status'], 'converted_original_deleted')

    @patch('lib.volvo_converter.find_lossless_files')
    def test_live_conversion_keeps_original_when_output_fails_validation(
        self,
        mock_find_lossless_files,
    ):
        from lib.volvo_converter import VolvoConverter

        flac = self.base / 'song.flac'
        flac.write_bytes(b'lossless')
        mock_find_lossless_files.return_value = [flac]

        converter = VolvoConverter(str(self.base), dry_run=False, manifest_file=None)
        output = self.base / 'song.m4a'
        def fake_run_ffmpeg(_ffmpeg_path, _input_path, output_path, timeout=300):
            output_path.write_bytes(b'partial-output')
            return True, 'Converted → song.m4a'

        with patch('lib.volvo_converter.run_ffmpeg', side_effect=fake_run_ffmpeg), \
             patch('lib.volvo_converter.validate_converted_output', return_value=(False, 'conversion produced a zero-byte output file')):
            converter.convert_all(ffmpeg_path='ffmpeg')

        self.assertTrue(flac.exists())
        self.assertFalse(output.exists())
        self.assertEqual(converter.manifest_rows[0]['status'], 'failed')
        self.assertEqual(converter.stats['failed'], 1)


class TestConverterMain(unittest.TestCase):

    @patch('lib.volvo_converter.VolvoConverter.convert_all')
    @patch('lib.volvo_converter.setup_logging', return_value=('logs/test.log', 'logs/test.csv'))
    @patch('lib.volvo_converter.check_ffmpeg')
    def test_main_dry_run_does_not_require_ffmpeg(
        self,
        mock_check_ffmpeg,
        _mock_setup_logging,
        mock_convert_all,
    ):
        import lib.volvo_converter as converter_module

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys, 'argv', ['volvo_converter.py', tmp]):
                converter_module.main()

        mock_check_ffmpeg.assert_not_called()
        mock_convert_all.assert_called_once_with('ffmpeg')

    @patch('lib.volvo_converter.VolvoConverter.convert_all')
    @patch('lib.volvo_converter.setup_logging', return_value=('logs/test.log', 'logs/test.csv'))
    @patch('lib.volvo_converter.check_ffmpeg', return_value='C:/ffmpeg/bin/ffmpeg.exe')
    def test_main_apply_requires_ffmpeg(
        self,
        mock_check_ffmpeg,
        _mock_setup_logging,
        mock_convert_all,
    ):
        import lib.volvo_converter as converter_module

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys, 'argv', ['volvo_converter.py', tmp, '--apply']):
                converter_module.main()

        mock_check_ffmpeg.assert_called_once_with()
        mock_convert_all.assert_called_once_with('C:/ffmpeg/bin/ffmpeg.exe')


if __name__ == '__main__':
    unittest.main()
