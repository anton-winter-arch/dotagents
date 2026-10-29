"""vault_patterns numbers lines on `\\n` only, the way grep and sed count them.

`str.splitlines()` also breaks on U+2028 and the other Unicode line separators, which
shifted every later line number and hid those characters from any check reading a body.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import vault_patterns as vp  # noqa: E402

LS = chr(0x2028)


class TestLinesOf(unittest.TestCase):
    def test_splits_on_newline_only(self):
        self.assertEqual(vp.lines_of(f'a{LS}b\nc\n'), [f'a{LS}b', 'c'])

    def test_matches_splitlines_on_plain_text(self):
        for text in ('', 'a', 'a\n', 'a\nb', 'a\n\nb\n', '\n'):
            self.assertEqual(vp.lines_of(text), text.splitlines(), repr(text))


class TestDateSectionsKeepSeparators(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.note = Path(self.tmp.name) / 'notes-x.md'
        self.note.write_text(f'# T\n\n## 2026-07-10\n\nOne{LS}two.\n\n## 2026-07-11\n\nNext.\n',
                             encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_body_keeps_the_separator(self):
        first = vp.date_sections(self.note)[0]
        self.assertIn(LS, first['body'])

    def test_line_numbers_follow_newlines(self):
        second = vp.date_sections(self.note)[1]
        self.assertEqual(second['start'], 7)
        self.assertTrue(vp.verify_range(self.note, 7, '2026-07-11'))


if __name__ == '__main__':
    unittest.main()
