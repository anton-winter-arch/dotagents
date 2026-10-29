"""Tests for the pure helpers in scripts/prior_state.py. The graph calls themselves go
through the markdown-kg skill's CLI, which lives beside this skill."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prior_state as ps  # noqa: E402


class TestTerms(unittest.TestCase):
    def test_identifier_like_keeps_names_and_drops_words(self):
        for t in ['username_key', 'webapps_gl_transactions.sql', 'ConfigLoader',
                  '<source-system>[-<company>]-<field>', 'b0c0272']:
            self.assertTrue(ps.identifier_like(t), t)
        for t in ['main', 'overwrite', 'true', 'ab_']:
            self.assertFalse(ps.identifier_like(t), t)

    def test_terms_split_work_items_from_other_identifiers(self):
        items, other = ps.terms_of(
            'STORY-1234 moved `export_job` to `main`; ADR-003 still Proposed.')
        self.assertEqual(items, {'STORY-1234'})
        self.assertEqual(other, {'export_job', 'ADR-003'})


class TestShapes(unittest.TestCase):
    def test_subsections_split_on_h3(self):
        body = '## 2026-03-16 - entry\n\n### First\nOne.\n\n### Second\nTwo.\n'
        self.assertEqual([h for h, _ in ps.subsections(body)], ['First', 'Second'])

    def test_section_date_falls_back_to_the_heading_path(self):
        self.assertEqual(ps.section_date({'note_id': 'notes-learnings',
                                          'heading_path': 'M > 2026-03-13 - x > Y'}),
                         '2026-03-13')
        self.assertEqual(ps.section_date({'note_id': 'notes-meeting-notes',
                                          'doc_date': '2026-03-10', 'heading_path': ''}),
                         '2026-03-10')

    def test_current_state_documents_are_undated(self):
        self.assertEqual(ps.section_date({'note_id': 'user-runsheet',
                                          'doc_date': '2026-02-01', 'heading_path': ''}), '')

    def test_the_run_sheet_is_not_an_authored_note(self):
        for name in ('user-runsheet', 'user-stories-runsheet', 'user-stories-tasks'):
            self.assertTrue(name.startswith(ps.NOT_AUTHORED), name)

    def test_the_engine_is_the_sibling_markdown_kg_skill(self):
        self.assertEqual(ps.KG.parent.parent.name, 'markdown-kg')
        self.assertEqual(ps.KG.parent.parent.parent, Path(ps.__file__).resolve().parents[2])

    def test_cited_entries_are_found_by_their_date(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'notes-learnings.md').write_text(
                '# L\n\n## 2026-03-16 - today\n### X\nBody.\n\n'
                '## 2026-03-11 - older\n### Y\nBody.\n', encoding='utf-8')
            got = ps.cited_entries(Path(d), 'as the 2026-03-11 entry recorded', '2026-03-16')
            self.assertEqual([s['date'] for s in got], ['2026-03-11'])

    def test_deepest_drops_a_parent_whose_child_also_hit(self):
        parent = {'note_id': 'n', 'heading_path': 'A > B'}
        child = {'note_id': 'n', 'heading_path': 'A > B > C'}
        other = {'note_id': 'm', 'heading_path': 'A > B'}
        kept = ps.deepest([(parent, set()), (child, set()), (other, set())])
        self.assertEqual([h for h, _ in kept], [child, other])

    def test_own_text_stops_at_the_first_child_heading(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'n.md').write_text(
                '# T\n## Title with ADR-003\nown line\n### Child\nchild line\n',
                encoding='utf-8')
            own = ps.own_text(Path(d), {'note_id': 'n', 'lines': '2-5'})
            self.assertIn('own line', own)
            self.assertNotIn('child line', own)


class TestGraphRequired(unittest.TestCase):
    def test_a_vault_without_a_graph_stops_the_run(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'notes-meetings.md').write_text('# M\n\n## 2026-03-16-STANDUP\nBody.\n',
                                                       encoding='utf-8')
            self.assertEqual(ps.main([d, '--today', '2026-03-16']), 2)


if __name__ == '__main__':
    unittest.main()
