"""
Property-based and edge-case fuzz tests for filename transformation functions.

Uses hypothesis to generate arbitrary inputs and verify that invariants hold
regardless of what filenames appear on the USB drive.  Hypothesis will shrink
failing inputs to the minimal reproducible example automatically.

Invariants tested:
  _shorten_filename:
        1. Result is never longer than the input (we never make it worse)
        2. Result length is ≤ MAX_FILENAME_LENGTH (64) when extension is ≤ 5 chars
        3. Calling it twice gives the same result (idempotent)
        4. The file extension is always preserved

  _fix_invalid_chars:
    1. Calling it twice gives the same result (idempotent)
    2. Every character listed in CHAR_REPLACEMENTS is absent from the result
"""

import sys
import unittest
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.volvo_path_fixer import VolvoPathFixer

# ---------------------------------------------------------------------------
# Shared lightweight fixer (no filesystem access needed for pure functions)
# ---------------------------------------------------------------------------

_fixer = VolvoPathFixer.__new__(VolvoPathFixer)
_fixer.CHAR_REPLACEMENTS = VolvoPathFixer.CHAR_REPLACEMENTS
_fixer.WORD_REPLACEMENTS = VolvoPathFixer.WORD_REPLACEMENTS
_fixer.MAX_FILENAME_LENGTH = VolvoPathFixer.MAX_FILENAME_LENGTH
_fixer.MAX_PATH_LENGTH = VolvoPathFixer.MAX_PATH_LENGTH

# ---------------------------------------------------------------------------
# Property tests: _shorten_filename
# ---------------------------------------------------------------------------

class TestShortFilenameProperties(unittest.TestCase):

    @given(st.text(min_size=1, max_size=300))
    def test_result_is_never_longer_than_input(self, filename):
        """Shortening should never increase the length."""
        result = _fixer._shorten_filename(filename)
        self.assertLessEqual(len(result), len(filename),
                             f"Input {len(filename)} chars, result {len(result)} chars: {result!r}")

    @given(st.from_regex(r'[^\x00/\\]{0,200}\.[a-z0-9]{1,5}', fullmatch=True))
    def test_result_within_limit_for_short_extensions(self, filename):
        """When the extension is short (audio-realistic), result must be ≤ 64 chars."""
        result = _fixer._shorten_filename(filename)
        self.assertLessEqual(len(result), VolvoPathFixer.MAX_FILENAME_LENGTH,
                             f"Got {len(result)} chars: {result!r}")

    @given(st.text(min_size=1, max_size=300))
    def test_is_idempotent(self, filename):
        once = _fixer._shorten_filename(filename)
        twice = _fixer._shorten_filename(once)
        self.assertEqual(once, twice, "Calling _shorten_filename twice must give the same result")

    @given(st.from_regex(r'[^\x00/\\]{0,200}\.[a-z0-9]{1,5}', fullmatch=True))
    def test_file_extension_is_preserved(self, filename):
        ext = Path(filename).suffix
        result = _fixer._shorten_filename(filename)
        self.assertEqual(
            Path(result).suffix,
            ext,
            f"Extension {ext!r} was lost or changed in result {result!r}",
        )


# ---------------------------------------------------------------------------
# Property tests: _fix_invalid_chars
# ---------------------------------------------------------------------------

class TestFixInvalidCharsProperties(unittest.TestCase):

    @given(st.text())
    def test_is_idempotent(self, text):
        once = _fixer._fix_invalid_chars(text)
        twice = _fixer._fix_invalid_chars(once)
        self.assertEqual(once, twice, "Calling _fix_invalid_chars twice must give the same result")

    @given(st.text())
    def test_all_known_replaceable_chars_are_removed(self, text):
        result = _fixer._fix_invalid_chars(text)
        for char in VolvoPathFixer.CHAR_REPLACEMENTS:
            self.assertNotIn(
                char,
                result,
                f"Character {char!r} (U+{ord(char):04X}) still present after replacement",
            )


# ---------------------------------------------------------------------------
# Edge-case table: explicit tricky filenames
# ---------------------------------------------------------------------------

# (description, filename)
# Separate set of cases where even the length-limit test applies
_EDGE_CASES_PATHOLOGICAL = [
    # Extension longer than the full limit — function returns unchanged, extension preserved
    ("very long extension", "a." + "x" * 65),
]

_EDGE_CASES = [
    # Boundary lengths
    ("exactly at limit",          "A" * 60 + ".mp3"),
    ("one over limit",            "A" * 61 + ".mp3"),
    ("way over limit",            "A" * 200 + ".mp3"),
    # Extension edge cases
    ("no stem dotfile",           ".mp3"),
    ("no extension",              "trackname"),
    ("multi-dot name",            "01.02.track.name.mp3"),
    # Track number patterns
    ("track num only",            "01.mp3"),
    ("track num almost too long", "01. " + "A" * 60 + ".mp3"),
    ("all-digits stem",           "1" * 80 + ".mp3"),
    ("track num itself too long", "1" * 70 + ".mp3"),
    # Character replacement edge cases
    ("all replaceable chars",     "".join(VolvoPathFixer.CHAR_REPLACEMENTS.keys()) + ".mp3"),
    ("mix of accented + long",    "é" * 40 + ".mp3"),
    ("replacement makes longer",  "¼¼¼¼¼¼¼¼¼¼¼¼¼¼.mp3"),   # ¼ → "1-4" (3x longer)
    # Unusual names
    ("windows reserved CON",      "CON.mp3"),
    ("windows reserved NUL",      "NUL.mp3"),
    ("spaces only stem",          "   .mp3"),
    ("single dot",                "."),
    ("just a space",              " "),
]


class TestEdgeCases(unittest.TestCase):

    def test_shorten_never_exceeds_limit(self):
        for description, filename in _EDGE_CASES:
            with self.subTest(case=description):
                result = _fixer._shorten_filename(filename)
                self.assertLessEqual(
                    len(result),
                    VolvoPathFixer.MAX_FILENAME_LENGTH,
                    f"[{description}] Got {len(result)} chars: {result!r}",
                )

    def test_pathological_extension_returned_unchanged(self):
        """When extension alone exceeds the limit, return input unmodified."""
        for description, filename in _EDGE_CASES_PATHOLOGICAL:
            with self.subTest(case=description):
                result = _fixer._shorten_filename(filename)
                self.assertEqual(result, filename,
                                 f"[{description}] Expected unchanged input, got {result!r}")

    def test_shorten_is_idempotent(self):
        for description, filename in _EDGE_CASES:
            with self.subTest(case=description):
                once = _fixer._shorten_filename(filename)
                twice = _fixer._shorten_filename(once)
                self.assertEqual(
                    once,
                    twice,
                    f"[{description}] Not idempotent: first={once!r}, second={twice!r}",
                )

    def test_fix_chars_then_shorten_stays_within_limit(self):
        for description, filename in _EDGE_CASES:
            with self.subTest(case=description):
                fixed = _fixer._fix_invalid_chars(filename)
                shortened = _fixer._shorten_filename(fixed)
                self.assertLessEqual(
                    len(shortened),
                    VolvoPathFixer.MAX_FILENAME_LENGTH,
                    f"[{description}] Pipeline result {len(shortened)} chars: {shortened!r}",
                )

    def test_fix_chars_is_idempotent(self):
        for description, filename in _EDGE_CASES:
            with self.subTest(case=description):
                once = _fixer._fix_invalid_chars(filename)
                twice = _fixer._fix_invalid_chars(once)
                self.assertEqual(
                    once,
                    twice,
                    f"[{description}] Not idempotent: first={once!r}, second={twice!r}",
                )


if __name__ == '__main__':
    unittest.main()
