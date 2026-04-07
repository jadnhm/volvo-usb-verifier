"""
Tests for volvo_usb_cleaner.py

Covers: junk file detection (macOS and Windows artifacts), dry-run safety,
and apply-mode deletion.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from volvo_usb_cleaner import VolvoUSBCleaner


class TestCleanerScan(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _scan(self) -> VolvoUSBCleaner:
        c = VolvoUSBCleaner(str(self.base), dry_run=True)
        c.scan()
        return c

    def test_finds_ds_store(self):
        (self.base / '.DS_Store').write_bytes(b'')
        c = self._scan()
        self.assertIn('.DS_Store', [f.name for f, _ in c.junk_files])

    def test_finds_thumbs_db(self):
        (self.base / 'Thumbs.db').write_bytes(b'')
        c = self._scan()
        self.assertIn('Thumbs.db', [f.name for f, _ in c.junk_files])

    def test_finds_desktop_ini(self):
        (self.base / 'desktop.ini').write_bytes(b'')
        c = self._scan()
        self.assertIn('desktop.ini', [f.name for f, _ in c.junk_files])

    def test_finds_autorun_inf(self):
        (self.base / 'autorun.inf').write_bytes(b'')
        c = self._scan()
        self.assertIn('autorun.inf', [f.name for f, _ in c.junk_files])

    def test_finds_macos_resource_fork(self):
        (self.base / '._song.mp3').write_bytes(b'')
        c = self._scan()
        self.assertIn('._song.mp3', [f.name for f, _ in c.junk_files])

    def test_dot_underscore_alone_not_flagged(self):
        # '._' with nothing after it is not a resource fork
        (self.base / '._').write_bytes(b'')
        c = self._scan()
        names = [f.name for f, _ in c.junk_files]
        self.assertNotIn('._', names)

    def test_finds_macosx_dir(self):
        macosx = self.base / '__MACOSX'
        macosx.mkdir()
        (macosx / 'something').write_bytes(b'')
        c = self._scan()
        self.assertIn('__MACOSX', [d.name for d, _ in c.junk_dirs])

    def test_macosx_dir_contents_not_double_counted(self):
        macosx = self.base / '__MACOSX'
        macosx.mkdir()
        (macosx / 'inner.txt').write_bytes(b'')
        c = self._scan()
        # The __MACOSX dir should be in junk_dirs; inner file should NOT also
        # appear in junk_files (we skip descending into it)
        self.assertEqual(len(c.junk_dirs), 1)
        self.assertEqual(c.junk_files, [])

    def test_finds_spotlight_dir(self):
        spot = self.base / '.Spotlight-V100'
        spot.mkdir()
        c = self._scan()
        self.assertIn('.Spotlight-V100', [d.name for d, _ in c.junk_dirs])

    def test_finds_system_volume_information(self):
        svi = self.base / 'System Volume Information'
        svi.mkdir()
        c = self._scan()
        self.assertIn(
            'System Volume Information',
            [d.name for d, _ in c.junk_dirs],
        )

    def test_finds_chkdsk_found_dir(self):
        found = self.base / 'FOUND.000'
        found.mkdir()
        c = self._scan()
        self.assertIn('FOUND.000', [d.name for d, _ in c.junk_dirs])

    def test_audio_files_not_flagged(self):
        for name in ('song.mp3', 'track.m4a', 'album.wma'):
            (self.base / name).write_bytes(b'')
        c = self._scan()
        self.assertEqual(c.junk_files, [])
        self.assertEqual(c.junk_dirs, [])

    def test_nested_ds_store_found(self):
        subdir = self.base / 'music' / 'artist'
        subdir.mkdir(parents=True)
        (subdir / '.DS_Store').write_bytes(b'')
        c = self._scan()
        self.assertEqual(len(c.junk_files), 1)

    def test_case_insensitive_thumbs_db(self):
        (self.base / 'THUMBS.DB').write_bytes(b'')
        c = self._scan()
        names_lower = [f.name.lower() for f, _ in c.junk_files]
        self.assertIn('thumbs.db', names_lower)


class TestCleanerActions(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_does_not_delete(self):
        junk = self.base / '.DS_Store'
        junk.write_bytes(b'')
        VolvoUSBCleaner(str(self.base), dry_run=True).clean_all()
        self.assertTrue(junk.exists())

    def test_apply_deletes_file(self):
        junk = self.base / 'Thumbs.db'
        junk.write_bytes(b'')
        VolvoUSBCleaner(str(self.base), dry_run=False).clean_all()
        self.assertFalse(junk.exists())

    def test_apply_removes_directory(self):
        macosx = self.base / '__MACOSX'
        macosx.mkdir()
        (macosx / 'res').write_bytes(b'')
        VolvoUSBCleaner(str(self.base), dry_run=False).clean_all()
        self.assertFalse(macosx.exists())

    def test_apply_preserves_audio(self):
        mp3 = self.base / 'song.mp3'
        mp3.write_bytes(b'audio')
        junk = self.base / 'Thumbs.db'
        junk.write_bytes(b'')
        VolvoUSBCleaner(str(self.base), dry_run=False).clean_all()
        self.assertTrue(mp3.exists())
        self.assertFalse(junk.exists())


if __name__ == '__main__':
    unittest.main()
