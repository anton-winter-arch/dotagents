"""Tests for scripts/window.py and the loose dated-heading matcher it reads through in
scripts/vault_patterns.py."""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'window.py'
sys.path.insert(0, str(SCRIPT.parent))
import vault_patterns as vp  # noqa: E402
import window  # noqa: E402

TODAY = dt.date(2026, 3, 16)            # a Monday, so the previous weekday is 03-13

MEETINGS = """---
type: meeting_note
---
# MEETINGS

## 2026-03-16-STANDUP

The export job moves to the new schedule today. See STORY-1234.

## 2026-03-16 - planning, a heading with a spaced title

Planning notes.

---
## 2026-03-13-STANDUP

The export job stays on the old schedule.

## 2026-03-13-REVIEW

Review notes.

## 2026-03-11

Older notes.
"""

CHAT = """# CHAT

## 2026-03-16

Chat today.

## 2026-02-02-ALL

Old chat, weeks before today.
"""

EMAIL = """# EMAIL

## 2026-03-13

Nothing dated today in this file.
"""

UPDATES = """# UPDATES

## 2026-03-16 STANDUP-DIGEST

Only a today section, written with a space.
"""

LEARNINGS_WITH_TODAY = """# LEARNINGS

## 2026-03-16 - the export job moves

### The export job runs on the new schedule
Body.

### A second finding
Body.

## 2026-03-13 - earlier
### Older
Body.

## 2026-03-13 - a second entry the same day
### Also older
Body.

## 2026-03-10 - two dates back
### Oldest
Body.
"""

LEARNINGS_WITHOUT_TODAY = """# LEARNINGS

## 2026-03-13 - earlier
### Older
Body.
"""


def build_raw(root: Path, learnings: str | None = LEARNINGS_WITHOUT_TODAY) -> Path:
    raw = root / 'raw'
    raw.mkdir()
    (raw / 'notes-meeting-notes.md').write_text(MEETINGS, encoding='utf-8')
    (raw / 'notes-chat-notes-internal.md').write_text(CHAT, encoding='utf-8')
    (raw / 'notes-email-notes.md').write_text(EMAIL, encoding='utf-8')
    (raw / 'notes-updates.md').write_text(UPDATES, encoding='utf-8')
    if learnings is not None:
        (raw / 'notes-learnings.md').write_text(learnings, encoding='utf-8')
    return raw


def run(*argv) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        window.main([str(a) for a in argv])
    return buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class TestLooseHeadings(Base):
    def test_strict_mode_is_unchanged(self):
        raw = build_raw(self.root)
        secs = vp.date_sections(raw / 'notes-meeting-notes.md')
        self.assertEqual([(s['date'], s['suffix']) for s in secs],
                         [('2026-03-16', 'STANDUP'), ('2026-03-13', 'STANDUP'),
                          ('2026-03-13', 'REVIEW'), ('2026-03-11', '')])
        self.assertTrue(all(s['canonical'] for s in secs))

    def test_loose_mode_adds_headings_with_more_after_the_date(self):
        raw = build_raw(self.root)
        secs = vp.date_sections(raw / 'notes-meeting-notes.md', loose=True)
        spaced = [s for s in secs if not s['canonical']]
        self.assertEqual(len(spaced), 1)
        self.assertEqual(spaced[0]['date'], '2026-03-16')
        self.assertEqual(spaced[0]['suffix'], 'planning, a heading with a spaced title')

    def test_loose_mode_rejects_a_longer_digit_run(self):
        self.assertIsNone(vp.DATE_H2_LOOSE.match('## 2026-03-160'))
        self.assertIsNotNone(vp.DATE_H2_LOOSE.match('## 2026-03-16'))
        self.assertIsNotNone(vp.DATE_H2_LOOSE.match('## 2026-03-16: a title'))


class TestBaselineSelection(Base):
    def secs(self, name):
        raw = build_raw(self.root)
        return window.dated(raw / name, TODAY)[0]

    def test_baseline_is_every_section_on_the_previous_date(self):
        todays, base, baseline = window.today_and_baseline(
            self.secs('notes-meeting-notes.md'), TODAY)
        self.assertEqual(len(todays), 2)
        self.assertEqual(base, dt.date(2026, 3, 13))
        self.assertEqual([s['suffix'] for s in baseline], ['STANDUP', 'REVIEW'])

    def test_baseline_reaches_back_past_a_gap(self):
        todays, base, _ = window.today_and_baseline(
            self.secs('notes-chat-notes-internal.md'), TODAY)
        self.assertEqual(len(todays), 1)
        self.assertEqual(base, dt.date(2026, 2, 2))

    def test_a_file_with_nothing_today_contributes_nothing(self):
        self.assertEqual(window.today_and_baseline(
            self.secs('notes-email-notes.md'), TODAY), ([], None, []))

    def test_a_file_with_only_today_has_no_baseline(self):
        todays, base, baseline = window.today_and_baseline(
            self.secs('notes-updates.md'), TODAY)
        self.assertEqual(len(todays), 1)
        self.assertIsNone(base)
        self.assertEqual(baseline, [])

    def test_future_sections_are_ignored(self):
        secs = self.secs('notes-meeting-notes.md')
        self.assertEqual(window.today_and_baseline(secs, dt.date(2026, 3, 12))[0], [])


class TestLearningsEntry(Base):
    def test_present_entry_is_found_by_date_prefix(self):
        raw = build_raw(self.root, LEARNINGS_WITH_TODAY)
        entries, _, _ = window.learnings_state(raw, TODAY)
        self.assertEqual(len(entries), 1)
        self.assertIn('the export job moves', entries[0]['body'].splitlines()[0])

    def test_baseline_is_every_entry_on_the_previous_date(self):
        raw = build_raw(self.root, LEARNINGS_WITH_TODAY)
        _, base, baseline = window.learnings_state(raw, TODAY)
        self.assertEqual(base, dt.date(2026, 3, 13))
        self.assertEqual([s['body'].splitlines()[0] for s in baseline],
                         ['## 2026-03-13 - earlier', '## 2026-03-13 - a second entry the same day'])

    def test_baseline_is_listed_before_todays_entry_exists(self):
        raw = build_raw(self.root)
        entries, base, baseline = window.learnings_state(raw, TODAY)
        self.assertEqual(entries, [])
        self.assertEqual(base, dt.date(2026, 3, 13))
        self.assertEqual(len(baseline), 1)

    def test_absent_entry_and_absent_file(self):
        raw = build_raw(self.root)
        self.assertEqual(window.learnings_state(raw, TODAY)[0], [])
        (raw / 'notes-learnings.md').unlink()
        self.assertIsNone(window.learnings_state(raw, TODAY))


class TestDailyCli(Base):
    def test_daily_listing(self):
        raw = build_raw(self.root, LEARNINGS_WITH_TODAY)
        out = run(raw, '--today', TODAY)
        self.assertIn('today 2026-03-16  (pinned with --today)', out)
        self.assertIn('learnings: ## 2026-03-16 entry exists', out)
        self.assertIn('(2 subsection(s))', out)
        self.assertIn('learnings baseline 2026-03-13', out)
        self.assertIn('## 2026-03-13 - a second entry the same day', out)
        self.assertNotIn('two dates back', out)
        learnings_rows = [ln for ln in out.splitlines() if '## 2026-03-13 - ' in ln]
        self.assertEqual(len(learnings_rows), 2)
        self.assertFalse(any('non-canonical' in ln for ln in learnings_rows))
        self.assertIn('baseline 2026-03-13', out)
        self.assertIn('baseline 2026-02-02', out)
        self.assertIn('baseline: none, no earlier dated section', out)
        self.assertIn('not in this run (nothing dated 2026-03-16): notes-email-notes.md', out)
        self.assertIn('[non-canonical heading, no section key]', out)
        self.assertIn(f'vault {raw}', out)
        self.assertNotIn('receipt', out)
        self.assertIn('STORY-1234', out)
        self.assertNotIn('Older notes', out)
        self.assertNotIn('## 2026-03-11', out)

    def test_baseline_prints_before_today_within_a_file(self):
        raw = build_raw(self.root)
        out = run(raw, '--today', TODAY)
        block = out.split('notes-meeting-notes.md\n', 1)[1]
        self.assertLess(block.index('## 2026-03-13-STANDUP'), block.index('## 2026-03-16-STANDUP'))

    def test_learnings_file_is_never_a_harvest_input(self):
        raw = build_raw(self.root, LEARNINGS_WITH_TODAY)
        out = run(raw, '--today', TODAY)
        self.assertNotIn('\nnotes-learnings.md\n', out)

    def test_absent_learnings_entry_is_reported(self):
        raw = build_raw(self.root)
        self.assertIn('learnings: no ## 2026-03-16 entry yet', run(raw, '--today', TODAY))

    def test_nothing_dated_today(self):
        raw = build_raw(self.root)
        out = run(raw, '--today', '2026-03-17')
        self.assertIn('no section dated 2026-03-17 in any notes-* file', out)

    def test_ids_only_reads_today(self):
        raw = build_raw(self.root)
        self.assertEqual(run(raw, '--today', TODAY, '--ids-only'), 'STORY-1234\n')


class TestLookbackModes(Base):
    def test_today_only_has_no_baseline(self):
        raw = build_raw(self.root)
        out = run(raw, '--today-only', '--today', TODAY)
        self.assertIn('--today-only', out)
        self.assertNotIn('2026-03-13', out)

    def test_days_keeps_the_represented_date_window(self):
        raw = build_raw(self.root)
        out = run(raw, '--days', 3, '--today', TODAY)
        self.assertIn('last 4 represented dates per file', out)
        self.assertIn('## 2026-03-11', out)


class TestEndToEnd(Base):
    def cli(self, *argv):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, argv)],
                              capture_output=True, text=True, check=True).stdout

    def test_runtime_date_drives_the_default_run(self):
        raw = self.root / 'raw'
        raw.mkdir()
        today = dt.date.today().isoformat()
        (raw / 'notes-meeting-notes.md').write_text(
            f'# M\n\n## {today}-STANDUP\n\nToday.\n', encoding='utf-8')
        out = self.cli(raw)
        self.assertIn(f'today {today}  (runtime date)', out)
        self.assertIn(f'## {today}-STANDUP', out)

    def test_repeat_runs_are_identical(self):
        raw = build_raw(self.root, LEARNINGS_WITH_TODAY)
        self.assertEqual(self.cli(raw, '--today', TODAY), self.cli(raw, '--today', TODAY))

    def test_bad_directory_exits_nonzero(self):
        r = subprocess.run([sys.executable, str(SCRIPT), str(self.root / 'missing')],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
