"""
Tests for volvo_path_fixer.py

Covers: character replacement, word abbreviation, filename shortening,
track-number preservation, extension preservation, and collision detection.
"""

import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.volvo_path_fixer import VolvoPathFixer


def _make_fixer() -> VolvoPathFixer:
    """Return a VolvoPathFixer instance without hitting the filesystem."""
    fixer = VolvoPathFixer.__new__(VolvoPathFixer)
    fixer.CHAR_REPLACEMENTS = VolvoPathFixer.CHAR_REPLACEMENTS
    fixer.WORD_REPLACEMENTS = VolvoPathFixer.WORD_REPLACEMENTS
    fixer.MAX_FILENAME_LENGTH = VolvoPathFixer.MAX_FILENAME_LENGTH
    fixer.MAX_PATH_LENGTH = VolvoPathFixer.MAX_PATH_LENGTH
    return fixer


def _make_fixer_with_base(base: Path, dry_run: bool = False) -> VolvoPathFixer:
    """Return a VolvoPathFixer wired to a real temp directory."""
    fixer = VolvoPathFixer.__new__(VolvoPathFixer)
    fixer.CHAR_REPLACEMENTS = VolvoPathFixer.CHAR_REPLACEMENTS
    fixer.WORD_REPLACEMENTS = VolvoPathFixer.WORD_REPLACEMENTS
    fixer.MAX_FILENAME_LENGTH = VolvoPathFixer.MAX_FILENAME_LENGTH
    fixer.MAX_PATH_LENGTH = VolvoPathFixer.MAX_PATH_LENGTH
    fixer.csv_file = Path('dummy.csv')
    fixer.drive_path = base
    fixer.dry_run = dry_run
    fixer.manifest_file = None
    fixer.stats = defaultdict(int)
    fixer.fixed_files = []
    fixer.failed_files = []
    fixer.renamed_dirs = {}
    fixer.paths_too_long = []
    fixer.manifest_rows = []
    import logging
    fixer.logger = logging.getLogger('VolvoPathFixer_test')
    return fixer


class TestCharReplacements(unittest.TestCase):

    def setUp(self):
        self.fixer = _make_fixer()

    def test_accented_chars_replaced(self):
        result = self.fixer._fix_invalid_chars("Café.mp3")
        self.assertNotIn('é', result)
        self.assertIn('e', result)

    def test_multiple_accents(self):
        result = self.fixer._fix_invalid_chars("réservé.mp3")
        self.assertNotIn('é', result)
        self.assertEqual(result, "reserve.mp3")

    def test_umlaut_o_replaced(self):
        result = self.fixer._fix_invalid_chars("Röck.mp3")
        self.assertNotIn('ö', result)
        self.assertIn('o', result)

    def test_fraction_half(self):
        result = self.fixer._fix_invalid_chars("1½ Hours.mp3")
        self.assertNotIn('½', result)
        self.assertIn('1-2', result)

    def test_multiply_sign(self):
        result = self.fixer._fix_invalid_chars("AC×DC.mp3")
        self.assertNotIn('×', result)
        self.assertIn('x', result)

    def test_clean_path_unchanged(self):
        path = "music/artist/01 - Rock Song.mp3"
        self.assertEqual(self.fixer._fix_invalid_chars(path), path)

    def test_n_tilde(self):
        result = self.fixer._fix_invalid_chars("Niño.mp3")
        self.assertNotIn('ñ', result)
        self.assertIn('n', result)

    def test_cedilla(self):
        result = self.fixer._fix_invalid_chars("façade.mp3")
        self.assertNotIn('ç', result)
        self.assertIn('c', result)


class TestShortenFilename(unittest.TestCase):

    def setUp(self):
        self.fixer = _make_fixer()

    def test_short_filename_unchanged(self):
        name = "01 - Short Track.mp3"
        self.assertEqual(self.fixer._shorten_filename(name), name)

    def test_long_filename_within_limit(self):
        name = "01 - This Is A Very Long Track Name That Exceeds The Limit Significantly.mp3"
        result = self.fixer._shorten_filename(name)
        self.assertLessEqual(len(result), VolvoPathFixer.MAX_FILENAME_LENGTH)

    def test_extension_preserved(self):
        name = "01 - Very Very Very Very Long Track Name That Needs Shortening.mp3"
        result = self.fixer._shorten_filename(name)
        self.assertTrue(result.endswith(".mp3"), f"Extension lost: {result}")

    def test_track_number_preserved(self):
        name = "01 - This Is A Very Long Track Name That Certainly Exceeds Sixty Four Characters Total.mp3"
        result = self.fixer._shorten_filename(name)
        self.assertTrue(result.startswith("01"), f"Track number lost: {result}")

    def test_remastered_abbreviated(self):
        name = "Artist - Song Name (Remastered Edition Version 2024).mp3"
        result = self.fixer._shorten_filename(name)
        # Should be shorter after abbreviation
        self.assertLessEqual(len(result), VolvoPathFixer.MAX_FILENAME_LENGTH)

    def test_bitrate_bracket_removed_when_shortening(self):
        name = "The Best Of Instrumental Surf Rock Albums Compilation [320kbps CBR].nfo"
        result = self.fixer._shorten_filename(name)
        self.assertNotIn("320kbps", result)
        self.assertNotIn("CBR", result)
        self.assertLessEqual(len(result), VolvoPathFixer.MAX_FILENAME_LENGTH)

    def test_at320_removed_when_shortening(self):
        name = "01 - A Very Long Song Name That Needs Shortening Immediately @320.mp3"
        result = self.fixer._shorten_filename(name)
        self.assertNotIn("@320", result)
        self.assertTrue(result.startswith("01"), f"Track number lost: {result}")
        self.assertLessEqual(len(result), VolvoPathFixer.MAX_FILENAME_LENGTH)

    def test_short_filename_not_changed_just_for_bitrate_tag(self):
        name = "01 - Song [320kbps CBR].mp3"
        self.assertEqual(self.fixer._shorten_filename(name), name)

    def test_the_prefix_removed_on_abbreviation(self):
        name = "The Very Long Song Title With Words That Exceed Sixty Four Characters Easily.mp3"
        result = self.fixer._shorten_filename(name)
        self.assertNotIn("The ", result)

    def test_exactly_at_limit_unchanged(self):
        # 60 chars stem + 4 chars ".mp3" = 64 chars total
        stem = "A" * 60
        name = stem + ".mp3"
        self.assertEqual(len(name), 64)
        self.assertEqual(self.fixer._shorten_filename(name), name)

    def test_one_over_limit_gets_shortened(self):
        stem = "A" * 61
        name = stem + ".mp3"
        self.assertEqual(len(name), 65)
        result = self.fixer._shorten_filename(name)
        self.assertLessEqual(len(result), 64)


class TestCollisionDetection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_collision_in_apply_mode_generates_unique_name(self):
        """When the target name already exists, a _2 suffix is appended and no data is lost."""
        (self.base / 'Song.mp3').write_bytes(b'existing')
        source = self.base / 'S\u00f3ng.mp3'
        source.write_bytes(b'source')

        fixer = _make_fixer_with_base(self.base, dry_run=False)
        fixer._process_file('S\u00f3ng.mp3', [{'issue_type': 'Invalid Characters'}])

        self.assertTrue((self.base / 'Song_2.mp3').exists(), "Collision-safe rename should exist")
        self.assertFalse(source.exists(), "Source should be gone after rename")
        self.assertTrue((self.base / 'Song.mp3').exists(), "Existing file must be untouched")
        self.assertEqual(fixer.stats['collisions_resolved'], 1)

    def test_collision_chains_to_next_available_number(self):
        """When _2 also exists, increments to _3."""
        (self.base / 'Song.mp3').write_bytes(b'v1')
        (self.base / 'Song_2.mp3').write_bytes(b'v2')
        source = self.base / 'S\u00f3ng.mp3'
        source.write_bytes(b'source')

        fixer = _make_fixer_with_base(self.base, dry_run=False)
        fixer._process_file('S\u00f3ng.mp3', [{'issue_type': 'Invalid Characters'}])

        self.assertTrue((self.base / 'Song_3.mp3').exists())
        self.assertEqual(fixer.stats['collisions_resolved'], 1)

    def test_collision_in_dry_run_detects_without_touching_files(self):
        """In dry-run mode, collision is flagged in the manifest but nothing is moved."""
        (self.base / 'Song.mp3').write_bytes(b'existing')
        source = self.base / 'S\u00f3ng.mp3'
        source.write_bytes(b'source')

        fixer = _make_fixer_with_base(self.base, dry_run=True)
        fixer._process_file('S\u00f3ng.mp3', [{'issue_type': 'Invalid Characters'}])

        self.assertTrue(source.exists(), "Source must be untouched in dry-run")
        self.assertEqual(fixer.stats['collisions_resolved'], 1)
        self.assertIn('_2', fixer.manifest_rows[0]['new_path'])

    def test_no_collision_when_target_does_not_exist(self):
        """No _2 suffix when the target name is free."""
        source = self.base / 'S\u00f3ng.mp3'
        source.write_bytes(b'source')

        fixer = _make_fixer_with_base(self.base, dry_run=False)
        fixer._process_file('S\u00f3ng.mp3', [{'issue_type': 'Invalid Characters'}])

        self.assertTrue((self.base / 'Song.mp3').exists())
        self.assertEqual(fixer.stats['collisions_resolved'], 0)


if __name__ == '__main__':
    unittest.main()
