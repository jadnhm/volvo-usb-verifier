"""Tests for the top-level Volvo pipeline coordinator."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import volvo_pipeline


class TestCheckFfmpeg(unittest.TestCase):

    @patch('volvo_pipeline.shutil.which', return_value='ffmpeg')
    def test_check_ffmpeg_succeeds_when_present(self, _mock_which):
        volvo_pipeline.check_ffmpeg()

    @patch('volvo_pipeline.shutil.which', return_value=None)
    def test_check_ffmpeg_exits_when_missing(self, _mock_which):
        with self.assertRaises(SystemExit) as ctx:
            volvo_pipeline.check_ffmpeg()
        self.assertEqual(ctx.exception.code, 1)


class TestRunVerifier(unittest.TestCase):

    def test_run_verifier_accepts_issues_exit_when_fresh_csv_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            old_csv = log_dir / 'volvo_verify_drive_old.csv'
            old_csv.write_text('old', encoding='utf-8')
            fresh_csv = log_dir / 'volvo_verify_drive_new.csv'

            def fake_run_step(_command, _label, allowed_exit_codes=None):
                fresh_csv.write_text('new', encoding='utf-8')
                return volvo_pipeline.VERIFIER_EXIT_ISSUES_FOUND

            with patch('volvo_pipeline.run_step', side_effect=fake_run_step):
                result = volvo_pipeline.run_verifier('python', Path('.'), 'D:/', log_dir, 'Verify')

        self.assertEqual(result, fresh_csv)

    def test_run_verifier_refuses_stale_csv_when_no_fresh_report_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            stale_csv = log_dir / 'volvo_verify_drive_old.csv'
            stale_csv.write_text('old', encoding='utf-8')

            with patch('volvo_pipeline.run_step', return_value=volvo_pipeline.VERIFIER_EXIT_ISSUES_FOUND):
                with self.assertRaises(SystemExit) as ctx:
                    volvo_pipeline.run_verifier('python', Path('.'), 'D:/', log_dir, 'Verify')

        self.assertEqual(ctx.exception.code, volvo_pipeline.VERIFIER_EXIT_FATAL)


class TestMainOrchestration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir_index = 0
        self.run_dir_patcher = patch(
            'volvo_pipeline.create_run_output_dir',
            side_effect=self._fake_run_output_dir,
        )
        self.run_dir_patcher.start()

    def tearDown(self):
        self.run_dir_patcher.stop()
        self.tmp.cleanup()

    def _fake_run_output_dir(self, base_dir, prefix):
        path = Path(self.tmp.name) / f"{prefix}_{self.run_dir_index:02d}"
        self.run_dir_index += 1
        path.mkdir(parents=True, exist_ok=True)
        return path

    @patch('volvo_pipeline.run_id3_fixer')
    @patch('volvo_pipeline.run_converter')
    @patch('volvo_pipeline.run_path_fixer')
    @patch('volvo_pipeline.run_verifier')
    @patch('volvo_pipeline.run_folder_splitter')
    @patch('volvo_pipeline.run_cleaner')
    @patch('volvo_pipeline.check_ffmpeg')
    def test_main_wires_steps_in_order(
        self,
        mock_check_ffmpeg,
        mock_run_cleaner,
        mock_run_folder_splitter,
        mock_run_verifier,
        mock_run_path_fixer,
        mock_run_converter,
        mock_run_id3_fixer,
    ):
        mock_run_verifier.side_effect = [
            Path('logs/initial.csv'),
            Path('logs/post_path.csv'),
            Path('logs/post_convert.csv'),
            Path('logs/final.csv'),
        ]
        mock_run_path_fixer.return_value = Path('logs/path_manifest.csv')
        mock_run_converter.return_value = Path('logs/convert_manifest.csv')
        mock_run_folder_splitter.return_value = Path('logs/split_manifest.csv')

        argv = [
            'volvo_pipeline.py',
            'D:/',
            '--apply-clean',
            '--run-split',
            '--apply-split',
            '--split-group-size',
            '150',
            '--apply-path',
            '--apply-convert',
            '--keep-originals-convert',
            '--resume-convert',
            '--apply-id3',
        ]

        with patch.object(sys, 'argv', argv):
            volvo_pipeline.main()

        mock_check_ffmpeg.assert_called_once_with()
        mock_run_cleaner.assert_called_once()
        cleaner_args = mock_run_cleaner.call_args.args
        self.assertEqual(cleaner_args[2], 'D:/')
        self.assertTrue(cleaner_args[3])
        self.assertIsInstance(cleaner_args[4], Path)

        mock_run_folder_splitter.assert_called_once()
        split_args = mock_run_folder_splitter.call_args.args
        self.assertEqual(split_args[2], 'D:/')
        self.assertTrue(split_args[3])
        self.assertEqual(split_args[4], 150)
        self.assertIsInstance(split_args[5], Path)

        self.assertEqual(mock_run_verifier.call_count, 4)
        verifier_labels = [call.args[4] for call in mock_run_verifier.call_args_list]
        self.assertEqual(
            verifier_labels,
            [
                'Step 1: Verify drive state',
                'Step 3: Re-verify after path fixer',
                'Step 5: Re-verify after lossless conversion',
                'Step 7: Final verification',
            ],
        )

        path_args = mock_run_path_fixer.call_args.args
        self.assertEqual(path_args[2], Path('logs/initial.csv'))
        self.assertEqual(path_args[3], 'D:/')
        self.assertTrue(path_args[4])
        self.assertIsInstance(path_args[5], Path)

        convert_args = mock_run_converter.call_args.args
        self.assertEqual(convert_args[2], 'D:/')
        self.assertTrue(convert_args[3])
        self.assertTrue(convert_args[4])
        self.assertTrue(convert_args[5])
        self.assertIsInstance(convert_args[6], Path)

        id3_args = mock_run_id3_fixer.call_args.args
        self.assertEqual(id3_args[2], Path('logs/post_convert.csv'))
        self.assertEqual(id3_args[3], 'D:/')
        self.assertTrue(id3_args[4])
        self.assertIsInstance(id3_args[5], Path)

    @patch('volvo_pipeline.run_id3_fixer')
    @patch('volvo_pipeline.run_converter')
    @patch('volvo_pipeline.run_path_fixer')
    @patch('volvo_pipeline.run_verifier')
    @patch('volvo_pipeline.run_folder_splitter')
    @patch('volvo_pipeline.run_cleaner')
    @patch('volvo_pipeline.check_ffmpeg')
    def test_main_defaults_to_dry_run_flags(
        self,
        mock_check_ffmpeg,
        mock_run_cleaner,
        mock_run_folder_splitter,
        mock_run_verifier,
        mock_run_path_fixer,
        mock_run_converter,
        mock_run_id3_fixer,
    ):
        mock_run_verifier.side_effect = [
            Path('logs/initial.csv'),
            Path('logs/post_path.csv'),
            Path('logs/post_convert.csv'),
            Path('logs/final.csv'),
        ]
        mock_run_path_fixer.return_value = Path('logs/path_manifest.csv')
        mock_run_converter.return_value = Path('logs/convert_manifest.csv')

        with patch.object(sys, 'argv', ['volvo_pipeline.py', 'D:/']):
            volvo_pipeline.main()

        mock_check_ffmpeg.assert_not_called()
        self.assertFalse(mock_run_cleaner.call_args.args[3])
        self.assertFalse(mock_run_folder_splitter.called)
        self.assertFalse(mock_run_path_fixer.call_args.args[4])
        self.assertFalse(mock_run_converter.call_args.args[3])
        self.assertFalse(mock_run_converter.call_args.args[4])
        self.assertFalse(mock_run_converter.call_args.args[5])
        self.assertFalse(mock_run_id3_fixer.call_args.args[4])

    @patch('volvo_pipeline.run_id3_fixer')
    @patch('volvo_pipeline.run_converter')
    @patch('volvo_pipeline.run_path_fixer')
    @patch('volvo_pipeline.run_verifier')
    @patch('volvo_pipeline.run_folder_splitter')
    @patch('volvo_pipeline.run_cleaner')
    @patch('volvo_pipeline.check_ffmpeg')
    def test_apply_convert_requires_ffmpeg(
        self,
        mock_check_ffmpeg,
        mock_run_cleaner,
        mock_run_folder_splitter,
        mock_run_verifier,
        mock_run_path_fixer,
        mock_run_converter,
        mock_run_id3_fixer,
    ):
        mock_run_verifier.side_effect = [
            Path('logs/initial.csv'),
            Path('logs/post_path.csv'),
            Path('logs/post_convert.csv'),
            Path('logs/final.csv'),
        ]
        mock_run_path_fixer.return_value = Path('logs/path_manifest.csv')
        mock_run_converter.return_value = Path('logs/convert_manifest.csv')

        with patch.object(sys, 'argv', ['volvo_pipeline.py', 'D:/', '--apply-convert']):
            volvo_pipeline.main()

        mock_check_ffmpeg.assert_called_once_with()

    @patch('volvo_pipeline.run_id3_fixer')
    @patch('volvo_pipeline.run_converter')
    @patch('volvo_pipeline.run_path_fixer')
    @patch('volvo_pipeline.run_verifier')
    @patch('volvo_pipeline.run_folder_splitter')
    @patch('volvo_pipeline.run_cleaner')
    @patch('volvo_pipeline.check_ffmpeg')
    def test_skip_convert_avoids_ffmpeg_and_uses_post_path_csv(
        self,
        mock_check_ffmpeg,
        mock_run_cleaner,
        mock_run_folder_splitter,
        mock_run_verifier,
        mock_run_path_fixer,
        mock_run_converter,
        mock_run_id3_fixer,
    ):
        mock_run_verifier.side_effect = [
            Path('logs/initial.csv'),
            Path('logs/post_path.csv'),
            Path('logs/final.csv'),
        ]
        mock_run_path_fixer.return_value = Path('logs/path_manifest.csv')

        with patch.object(sys, 'argv', ['volvo_pipeline.py', 'D:/', '--skip-convert']):
            volvo_pipeline.main()

        mock_check_ffmpeg.assert_not_called()
        mock_run_converter.assert_not_called()
        mock_run_folder_splitter.assert_not_called()
        self.assertEqual(mock_run_verifier.call_count, 3)
        self.assertEqual(mock_run_id3_fixer.call_args.args[2], Path('logs/post_path.csv'))

    def test_resume_convert_requires_converter_step(self):
        with patch.object(sys, 'argv', ['volvo_pipeline.py', 'D:/', '--skip-convert', '--resume-convert']):
            with self.assertRaises(SystemExit) as ctx:
                volvo_pipeline.main()
        self.assertEqual(ctx.exception.code, 2)

    @patch('volvo_pipeline.run_id3_fixer')
    @patch('volvo_pipeline.run_converter')
    @patch('volvo_pipeline.run_path_fixer')
    @patch('volvo_pipeline.run_verifier')
    @patch('volvo_pipeline.run_folder_splitter')
    @patch('volvo_pipeline.run_cleaner')
    @patch('volvo_pipeline.check_ffmpeg')
    def test_config_file_sets_defaults(
        self,
        mock_check_ffmpeg,
        mock_run_cleaner,
        mock_run_folder_splitter,
        mock_run_verifier,
        mock_run_path_fixer,
        mock_run_converter,
        mock_run_id3_fixer,
    ):
        """INI config values are used when no CLI flag overrides them."""
        mock_run_verifier.side_effect = [
            Path('logs/initial.csv'),
            Path('logs/post_path.csv'),
            Path('logs/post_convert.csv'),
            Path('logs/final.csv'),
        ]
        mock_run_path_fixer.return_value = Path('logs/path_manifest.csv')
        mock_run_converter.return_value = Path('logs/convert_manifest.csv')

        ini_content = '[pipeline]\napply_id3 = true\nsplit_group_size = 99\n'
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.ini', delete=False, encoding='utf-8'
        ) as cfg_file:
            cfg_file.write(ini_content)
            cfg_path = cfg_file.name

        try:
            with patch.object(sys, 'argv', ['volvo_pipeline.py', 'D:/', '--config', cfg_path]):
                volvo_pipeline.main()
        finally:
            Path(cfg_path).unlink(missing_ok=True)

        # apply_id3 = true from config → run_id3_fixer called with apply=True
        self.assertTrue(mock_run_id3_fixer.call_args.args[4])
        # split_group_size was set but --run-split not passed, so splitter not called
        mock_run_folder_splitter.assert_not_called()


if __name__ == '__main__':
    unittest.main()