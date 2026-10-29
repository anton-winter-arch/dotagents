"""The TEAM roster parser: an empty table row is skipped, a person row with no alias still fails."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import vault_patterns  # noqa: E402

HEADER = ('| Alias | Code | Org | On project | Role |\n'
          '| ----- | ---- | --- | ---------- | ---- |\n')


class RosterTest(unittest.TestCase):
    def north_star(self, rows: str) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'north-star.md'
        path.write_text('# North star\n\n## TEAM\n\n' + HEADER + rows + '\n## NEXT\n', encoding='utf-8')
        return path

    def test_empty_row_is_skipped(self):
        people = vault_patterns.roster(self.north_star(
            '| AB | DE0 | internal | yes | Engineer |\n'
            '|    |     |          |     |          |\n'
            '| CD | DE1 | internal | no  | Analyst  |\n'))
        self.assertEqual(sorted(people), ['AB', 'CD'])
        self.assertTrue(people['AB']['on_project'])
        self.assertFalse(people['CD']['on_project'])

    def test_person_row_without_alias_still_fails(self):
        with self.assertRaises(vault_patterns.RosterError):
            vault_patterns.roster(self.north_star(
                '| AB | DE0 | internal | yes | Engineer |\n'
                '|    | DE1 | internal | yes | Analyst  |\n'))

    def test_only_empty_rows_still_fails(self):
        with self.assertRaises(vault_patterns.RosterError):
            vault_patterns.roster(self.north_star('|  |  |  |  |  |\n'))


if __name__ == '__main__':
    unittest.main()
