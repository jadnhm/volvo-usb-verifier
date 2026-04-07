"""
Tests for volvo_usb_fixer.py

Covers: stale-CSV warning logic and CSV loading.
"""

import csv
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.volvo_usb_fixer import VolvoUSBFixer


def _make_fixer(csv_path: str, drive_path: str) -> VolvoUSBFixer:
    """Return a VolvoUSBFixer without a full filesystem setup."""
    fixer = VolvoUSBFixer.__new__(VolvoUSBFixer)
    fixer.csv_file = Path(csv_path)
    fixer.drive_path = Path(drive_path)
    fixer.dry_run = True
    fixer.logger = MagicMock()
    fixer._messages = []
    fixer.log = lambda m: fixer._messages.append(m)
    return fixer


class TestWarnIfCsvStale(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.logs = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_csv(self, name: str) -> Path:
        p = self.logs / name
        p.write_text('file_path,issue_type,severity,description\n')
        return p

    def _write_manifest(self, name: str) -> Path:
        p = self.logs / name
        p.write_text('timestamp,source_csv,original_path,new_path,status,actions,warnings,error\n')
        return p

    def test_no_manifest_no_warning(self):
        csv_file = self._write_csv('volvo_verify_test.csv')
        fixer = _make_fixer(str(csv_file), self.tmp.name)
        fixer.warn_if_csv_may_be_stale()
        self.assertFalse(any('WARNING' in m for m in fixer._messages))

    def test_older_manifest_no_warning(self):
        csv_file = self._write_csv('volvo_verify_test.csv')
        manifest = self._write_manifest('volvo_path_manifest_20200101_000000.csv')

        # Push manifest into the past
        past = datetime.now().timestamp() - 3600
        os.utime(manifest, (past, past))
        # Ensure CSV is newer
        now = datetime.now().timestamp() + 1
        os.utime(csv_file, (now, now))

        fixer = _make_fixer(str(csv_file), self.tmp.name)
        fixer.warn_if_csv_may_be_stale()
        self.assertFalse(any('WARNING' in m for m in fixer._messages))

    def test_newer_manifest_warns(self):
        csv_file = self._write_csv('volvo_verify_test.csv')
        manifest = self._write_manifest('volvo_path_manifest_recent.csv')

        # Push CSV into the past so manifest is definitely newer
        past = datetime.now().timestamp() - 3600
        os.utime(csv_file, (past, past))

        fixer = _make_fixer(str(csv_file), self.tmp.name)
        fixer.warn_if_csv_may_be_stale()
        self.assertTrue(any('WARNING' in m for m in fixer._messages))


class TestLoadIssues(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_csv(self, rows: list) -> str:
        path = Path(self.tmp.name) / 'test.csv'
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(
                f, fieldnames=['file_path', 'issue_type', 'severity', 'description'])
            writer.writeheader()
            writer.writerows(rows)
        return str(path)

    def test_single_file_single_issue(self):
        csv_path = self._write_csv([
            {'file_path': 'music/test.mp3', 'issue_type': 'ID3 Tags',
             'severity': 'Warning', 'description': 'ID3v2.4'},
        ])
        fixer = VolvoUSBFixer(csv_path, self.tmp.name, dry_run=True)
        issues = fixer.load_issues()
        self.assertIn('music/test.mp3', issues)
        self.assertEqual(len(issues['music/test.mp3']), 1)

    def test_single_file_multiple_issues(self):
        csv_path = self._write_csv([
            {'file_path': 'music/test.mp3', 'issue_type': 'ID3 Tags',
             'severity': 'Warning', 'description': 'ID3v2.4'},
            {'file_path': 'music/test.mp3', 'issue_type': 'Album Art',
             'severity': 'Warning', 'description': 'Large artwork: 800 KB'},
        ])
        fixer = VolvoUSBFixer(csv_path, self.tmp.name, dry_run=True)
        issues = fixer.load_issues()
        self.assertEqual(len(issues['music/test.mp3']), 2)

    def test_multiple_files(self):
        csv_path = self._write_csv([
            {'file_path': 'music/a.mp3', 'issue_type': 'ID3 Tags',
             'severity': 'Warning', 'description': 'ID3v2.4'},
            {'file_path': 'music/b.mp3', 'issue_type': 'Album Art',
             'severity': 'Warning', 'description': 'Large artwork'},
        ])
        fixer = VolvoUSBFixer(csv_path, self.tmp.name, dry_run=True)
        issues = fixer.load_issues()
        self.assertEqual(len(issues), 2)

    def test_empty_csv(self):
        csv_path = self._write_csv([])
        fixer = VolvoUSBFixer(csv_path, self.tmp.name, dry_run=True)
        issues = fixer.load_issues()
        self.assertEqual(len(issues), 0)


if __name__ == '__main__':
    unittest.main()
