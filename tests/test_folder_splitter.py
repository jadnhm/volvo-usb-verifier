"""
Tests for volvo_folder_splitter.py

Covers: overcrowded folder detection, split planning, dry-run safety,
and apply-mode file movement.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.volvo_folder_splitter import VolvoFolderSplitter, MAX_FILES_PER_FOLDER


def _make_audio_files(folder: Path, count: int, ext: str = '.mp3'):
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (folder / f"track_{i:04d}{ext}").write_bytes(b'')


class TestFindOvercrowded(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_drive_no_result(self):
        s = VolvoFolderSplitter(str(self.base))
        self.assertEqual(s.find_overcrowded(), {})

    def test_small_folder_not_overcrowded(self):
        _make_audio_files(self.base / 'album', 10)
        self.assertEqual(VolvoFolderSplitter(str(self.base)).find_overcrowded(), {})

    def test_exactly_at_limit_not_overcrowded(self):
        _make_audio_files(self.base / 'album', MAX_FILES_PER_FOLDER)
        self.assertEqual(VolvoFolderSplitter(str(self.base)).find_overcrowded(), {})

    def test_one_over_limit_is_overcrowded(self):
        album = self.base / 'album'
        _make_audio_files(album, MAX_FILES_PER_FOLDER + 1)
        result = VolvoFolderSplitter(str(self.base)).find_overcrowded()
        self.assertIn(album, result)

    def test_overcrowded_count_correct(self):
        album = self.base / 'album'
        _make_audio_files(album, 300)
        result = VolvoFolderSplitter(str(self.base)).find_overcrowded()
        self.assertEqual(len(result[album]), 300)

    def test_non_audio_files_ignored(self):
        album = self.base / 'album'
        album.mkdir()
        for i in range(300):
            (album / f"image_{i}.jpg").write_bytes(b'')
        self.assertEqual(VolvoFolderSplitter(str(self.base)).find_overcrowded(), {})

    def test_multiple_overcrowded_folders_detected(self):
        for name in ('AlbumA', 'AlbumB'):
            _make_audio_files(self.base / name, 300)
        result = VolvoFolderSplitter(str(self.base)).find_overcrowded()
        self.assertEqual(len(result), 2)


class TestPlanSplits(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _files(self, names):
        return [self.base / f"{n}.mp3" for n in names]

    def test_300_files_with_200_group_size_gives_two_groups(self):
        files = self._files([f"track_{i:04d}" for i in range(300)])
        splits = VolvoFolderSplitter(str(self.base), group_size=200).plan_splits(files)
        self.assertEqual(len(splits), 2)

    def test_each_group_within_size_limit(self):
        files = self._files([f"track_{i:04d}" for i in range(500)])
        splits = VolvoFolderSplitter(str(self.base), group_size=200).plan_splits(files)
        for _, chunk in splits:
            self.assertLessEqual(len(chunk), 200)

    def test_all_files_accounted_for(self):
        total = 400
        files = self._files([f"track_{i:04d}" for i in range(total)])
        splits = VolvoFolderSplitter(str(self.base), group_size=200).plan_splits(files)
        self.assertEqual(sum(len(c) for _, c in splits), total)

    def test_group_names_are_unique(self):
        files = self._files([f"track_{i:04d}" for i in range(500)])
        splits = VolvoFolderSplitter(str(self.base), group_size=200).plan_splits(files)
        names = [n for n, _ in splits]
        self.assertEqual(len(names), len(set(names)))

    def test_single_overfull_group(self):
        files = self._files([f"track_{i:04d}" for i in range(300)])
        splits = VolvoFolderSplitter(str(self.base), group_size=300).plan_splits(files)
        self.assertEqual(len(splits), 1)
        self.assertEqual(len(splits[0][1]), 300)


class TestSplitAllDryRun(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_does_not_move_files(self):
        album = self.base / 'BigAlbum'
        _make_audio_files(album, 300)
        VolvoFolderSplitter(str(self.base), dry_run=True, group_size=200).split_all()
        # Files still in original location
        self.assertEqual(len(list(album.glob('*.mp3'))), 300)

    def test_dry_run_creates_no_subdirs(self):
        album = self.base / 'BigAlbum'
        _make_audio_files(album, 300)
        VolvoFolderSplitter(str(self.base), dry_run=True, group_size=200).split_all()
        subdirs = [d for d in album.iterdir() if d.is_dir()]
        self.assertEqual(subdirs, [])


class TestSplitAllApply(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_apply_moves_all_files(self):
        album = self.base / 'BigAlbum'
        _make_audio_files(album, 300)
        VolvoFolderSplitter(str(self.base), dry_run=False, group_size=200).split_all()
        # No .mp3 files left directly in album root
        self.assertEqual(len(list(album.glob('*.mp3'))), 0)
        # All 300 files accessible recursively
        self.assertEqual(len(list(album.rglob('*.mp3'))), 300)

    def test_apply_respects_group_size(self):
        album = self.base / 'BigAlbum'
        _make_audio_files(album, 300)
        VolvoFolderSplitter(str(self.base), dry_run=False, group_size=100).split_all()
        subdirs = [d for d in album.iterdir() if d.is_dir()]
        for sd in subdirs:
            self.assertLessEqual(len(list(sd.glob('*.mp3'))), 100)

    def test_apply_creates_manifest(self):
        album = self.base / 'BigAlbum'
        _make_audio_files(album, 300)
        manifest = self.base / 'split_manifest.csv'
        s = VolvoFolderSplitter(
            str(self.base), dry_run=False, group_size=200,
            manifest_file=str(manifest),
        )
        s.split_all()
        self.assertTrue(manifest.exists())


if __name__ == '__main__':
    unittest.main()
