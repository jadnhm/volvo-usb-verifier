"""Tests for audiobook helper functions that do not require Claude CLI."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.audiobooks.rename_audiobooks import find_audiobook_files as find_single_files
from lib.audiobooks.rename_audiobooks_batch import (
    apply_pattern_to_file,
    extract_track_number,
    find_audiobook_files as find_batch_files,
    group_files_by_book,
)


class TestExtractTrackNumber(unittest.TestCase):

    def test_extracts_disc_track_pattern(self):
        self.assertEqual(extract_track_number('1-03 Ch 3.mp3'), '1-03')

    def test_extracts_chapter_pattern(self):
        self.assertEqual(extract_track_number('Chapter 07 - Example.mp3'), '07')

    def test_extracts_of_pattern(self):
        self.assertEqual(extract_track_number('Brave New World - 01 of 10.mp3'), '01')

    def test_returns_none_when_no_pattern_found(self):
        self.assertIsNone(extract_track_number('Introduction.mp3'))


class TestAudiobookFileDiscovery(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / 'VOLVO' / 'books'
        self.base.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_both_discovery_functions_find_only_mp3_files(self):
        (self.base / '1984').mkdir()
        (self.base / '1984' / '01.mp3').write_bytes(b'')
        (self.base / '1984' / '02.mp3').write_bytes(b'')
        (self.base / '1984' / 'cover.jpg').write_bytes(b'')

        self.assertEqual(len(find_single_files(self.base)), 2)
        self.assertEqual(len(find_batch_files(self.base)), 2)


class TestGroupFilesByBook(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / 'VOLVO' / 'books'
        self.base.mkdir(parents=True)

        self.first_book = self.base / '1984 (George Orwell) - Audio Book'
        self.first_book.mkdir()
        self.second_book = self.base / 'Gullivers Travels'
        self.second_book.mkdir()

        self.files = [
            self.first_book / 'Audio Books - George Orwell - 1984 - 1 of 14.mp3',
            self.first_book / 'Audio Books - George Orwell - 1984 - 2 of 14.mp3',
            self.second_book / '01 Voyage to Liliput.mp3',
        ]
        for file_path in self.files:
            file_path.write_bytes(b'')

    def tearDown(self):
        self.tmp.cleanup()

    def test_groups_by_parent_directory(self):
        groups = group_files_by_book(self.files, self.base)
        self.assertEqual(len(groups), 2)
        self.assertIn('books/1984 (George Orwell) - Audio Book', groups)
        self.assertIn('books/Gullivers Travels', groups)
        self.assertEqual(len(groups['books/1984 (George Orwell) - Audio Book']), 2)


class TestApplyPatternToFile(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / 'VOLVO' / 'books'
        self.base.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_applies_simple_numeric_pattern(self):
        sample = self.base / '1984 (George Orwell) - Audio Book' / 'Audio Books - George Orwell - 1984 - 1 of 14.mp3'
        target = self.base / '1984 (George Orwell) - Audio Book' / 'Audio Books - George Orwell - 1984 - 2 of 14.mp3'
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_bytes(b'')
        target.write_bytes(b'')

        result = apply_pattern_to_file(target, sample, 'books/1984/01.mp3', self.base)
        self.assertEqual(result, 'books/1984/02.mp3')

    def test_preserves_disc_number_when_pattern_uses_disc_track(self):
        sample = self.base / 'The Hobbit Audiobook' / 'The Hobbit (Disc 01)' / '1-01 Ch 1a, An Unexpected Party.mp3'
        target = self.base / 'The Hobbit Audiobook' / 'The Hobbit (Disc 01)' / '1-02 Ch 1b, More Party.mp3'
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_bytes(b'')
        target.write_bytes(b'')

        result = apply_pattern_to_file(target, sample, 'books/Hobbit/1-01.mp3', self.base)
        self.assertEqual(result, 'books/Hobbit/1-02.mp3')


if __name__ == '__main__':
    unittest.main()