"""Tests for scripts/comment_lint.py: block extraction, the lexical floors, and the CLI."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'comment_lint.py'
sys.path.insert(0, str(SCRIPT.parent))
import comment_lint as cl  # noqa: E402

NOTE = """# PR REVIEWS

## PR-STORY-000001-AB-2026-01-01
PR 42

**PR COMMENTS**
```
CD 2026-01-01
looks fine to me
```

**COMMENTS-DRAFT**
```
(models/staging.sql LINES 10-12)
the staging model points at the new source, so the backfill reads it twice.
let's plan to confirm in standup tomorrow.
```

## PR-STORY-000002-AB-2026-01-02

**COMMENTS-DRAFT**
```
second draft
```
"""


class TestExtract(unittest.TestCase):
    def test_extracts_the_draft_block_of_the_named_section(self):
        body = cl.extract(NOTE, 'PR-STORY-000001-AB-2026-01-01')
        self.assertIn('the staging model points at the new source', body)
        self.assertNotIn('looks fine to me', body)
        self.assertNotIn('second draft', body)

    def test_no_block_name_returns_the_whole_text(self):
        self.assertEqual(cl.extract('plain draft', None), 'plain draft')

    def test_missing_block_exits(self):
        with self.assertRaises(SystemExit):
            cl.extract(NOTE, 'PR-STORY-000009-AB-2026-01-01')

    def test_thread_labels_are_dropped(self):
        body = cl.drop_labels(cl.extract(NOTE, 'PR-STORY-000001-AB-2026-01-01'))
        self.assertNotIn('LINES 10-12', body)
        self.assertIn('backfill reads it twice', body)


class TestFloors(unittest.TestCase):
    def test_clean_draft_has_no_findings(self):
        self.assertEqual(cl.check('the staging model points at the new source.\nlet\'s confirm tomorrow.'), [])

    def test_sneer_factional_and_severity_words_are_found(self):
        found = cl.check('obviously our copy is broken.')
        labels = {f.split(':')[0] for f in found}
        self.assertEqual(labels, {'sneer', 'factional pronoun', 'severity word'})

    def test_numbered_questions_read_as_an_audit(self):
        found = cl.check('1. why is this here?\n2. and this?')
        self.assertEqual(len([f for f in found if f.startswith('numbered')]), 2)

    def test_mid_sentence_title_case_is_found_but_identifiers_are_not(self):
        self.assertEqual(cl.check('the Staging Model is fine'),
                         ['capitalized mid-sentence: Staging', 'capitalized mid-sentence: Model'])
        self.assertEqual(cl.check('the DBT_SEEDS folder and models/staging.sql and AB and a1b2c3d are fine'), [])

    def test_code_spans_are_ignored(self):
        self.assertEqual(cl.check('see `Obviously_Broken` for the value'), [])

    def test_shape_reports_length_only(self):
        self.assertEqual(cl.shape('one two? three\n\nfour'), '4 words, 1 questions, 2 paragraphs')


class TestCli(unittest.TestCase):
    def run_cli(self, *argv):
        return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True)

    def test_clean_block_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'notes-pr-reviews.md'
            p.write_text(NOTE, encoding='utf-8')
            r = self.run_cli(str(p), '--block', 'PR-STORY-000001-AB-2026-01-01')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('clean', r.stdout)

    def test_findings_exit_one(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'draft.txt'
            p.write_text('this is clearly broken on your side.\n', encoding='utf-8')
            r = self.run_cli(str(p))
            self.assertEqual(r.returncode, 1)
            self.assertIn('finding(s)', r.stdout)


if __name__ == '__main__':
    unittest.main()
