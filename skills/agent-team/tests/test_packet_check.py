"""packet_check.py against real git repos built per test from tests/fixtures/board.md.

Each repo has three commits: base (app.py and the board), head (an app.py change)
and the board commit (the evidence entry appended to the story's COMMENTS).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import packet_check  # noqa: E402

BOARD = (HERE / "fixtures" / "board.md").read_text(encoding="utf-8")
STORY = "STORY-NNNN03"
FENCE = "````\n"

GOOD = (
    "- evidence {head} base {base} security safe\n"
    "  - criteria:1 pass outcome_test.py: 3 passed\n"
    "  - criteria:2 pass restart_test.py: 1 passed\n"
    "  - validation:1 pass outcome_test.py: 3 passed\n"
    "  - dod:1 manual the user confirms the runbook page\n"
)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                           "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def append_comments(board, text):
    """Insert text before the closing fence of the board's last block (the story's COMMENTS)."""
    at = board.rindex(FENCE)
    return board[:at] + text + board[at:]


class Repo:
    def __init__(self, tmp, board="board.md"):
        self.path, self.board = Path(tmp), board
        git(self.path, "init", "-q", "-b", "main")
        self.write("app.py", "v = 1\n")
        self.write(board, BOARD)
        self.base = self.commit("base")
        self.write("app.py", "v = 2\n")
        self.head = self.commit("head")

    def write(self, name, text):
        (self.path / name).write_text(text, encoding="utf-8")

    def commit(self, msg):
        git(self.path, "add", "-A")
        git(self.path, "commit", "-q", "-m", msg)
        return git(self.path, "rev-parse", "HEAD")

    def board_commit(self, entry, board=None):
        text = append_comments(board or BOARD, entry.format(head=self.head, base=self.base))
        self.write(self.board, text)
        return self.commit("board")

    def check(self, board_at, head=None, story=STORY, assigned_at=None):
        return packet_check.check(self.path, self.board, story, head or self.head, board_at,
                                  assigned_at or self.base)


def plain_run(argv, *, timeout, **kw):
    """procguard.run without its watchdog, which costs about 0.3 s per spawn. The
    in-process tests check logic; TestCli runs the script, and procguard, for real."""
    return subprocess.run(argv, timeout=timeout, **kw)


class PacketCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(self._tmp.name)
        self._run, packet_check.procguard.run = packet_check.procguard.run, plain_run

    def tearDown(self):
        packet_check.procguard.run = self._run
        self._tmp.cleanup()

    def codes(self, problems):
        return [p["code"] for p in problems]


class TestComplete(PacketCheckTest):
    def test_complete_delivery_has_no_problems(self):
        self.assertEqual(self.repo.check(self.repo.board_commit(GOOD)), [])

    def test_abbreviated_shas_are_accepted(self):
        entry = GOOD.replace("{head}", "{head:.12}").replace("{base}", "{base:.12}")
        self.assertEqual(self.repo.check(self.repo.board_commit(entry)), [])

    def test_free_text_lines_are_ignored(self):
        self.assertEqual(self.repo.check(self.repo.board_commit("lead asked for a rerun\n" + GOOD)), [])

    def test_later_entry_for_the_same_head_counts(self):
        bad = GOOD.replace("  - dod:1 manual the user confirms the runbook page\n", "")
        self.assertEqual(self.repo.check(self.repo.board_commit(bad + GOOD)), [])
        self.assertIn("missing-item", self.codes(self.repo.check(self.repo.board_commit(GOOD + bad))))


class TestEvidence(PacketCheckTest):
    def test_no_entry_for_the_head(self):
        problems = self.repo.check(self.repo.board_commit(GOOD.replace("{head}", "{base}")))
        self.assertEqual(self.codes(problems), ["no-evidence"])

    def test_missing_item_names_the_board_line(self):
        entry = GOOD.replace("  - validation:1 pass outcome_test.py: 3 passed\n", "")
        problems = self.repo.check(self.repo.board_commit(entry))
        self.assertEqual(self.codes(problems), ["missing-item"])
        line = BOARD.splitlines().index("- [ ] outcome_test.py passes") + 1
        self.assertEqual(problems[0]["line"], line)

    def test_duplicate_item(self):
        entry = GOOD + "  - criteria:1 pass again\n"
        self.assertEqual(self.codes(self.repo.check(self.repo.board_commit(entry))), ["duplicate-item"])

    def test_item_out_of_range(self):
        entry = GOOD + "  - criteria:3 pass no such criterion\n"
        self.assertEqual(self.codes(self.repo.check(self.repo.board_commit(entry))), ["out-of-range"])

    def test_malformed_items(self):
        for item in ("  - criteria:1 passed fine\n", "  - crit:1 pass x\n", "  - criteria:1 pass\n",
                     "  - criteria:x pass y\n"):
            with self.subTest(item=item):
                entry = GOOD.replace("  - criteria:1 pass outcome_test.py: 3 passed\n", item)
                codes = self.codes(self.repo.check(self.repo.board_commit(entry)))
                self.assertEqual(codes, ["bad-item", "missing-item"])

    def test_bad_item_names_its_comments_line(self):
        board_at = self.repo.board_commit(GOOD + "  - dod:1 pass\n")
        bad = [p for p in self.repo.check(board_at) if p["code"] == "bad-item"][0]
        text = git(self.repo.path, "show", f"{board_at}:board.md").splitlines()
        self.assertEqual(text[bad["line"] - 1], "  - dod:1 pass")

    def test_missing_security_token_is_a_bad_header(self):
        entry = GOOD.replace(" security safe", "")
        self.assertEqual(self.codes(self.repo.check(self.repo.board_commit(entry))),
                         ["bad-header", "no-evidence"])

    def test_blocked_security_fails_and_pending_does_not(self):
        blocked = self.repo.board_commit(GOOD.replace("security safe", "security blocked"))
        self.assertEqual(self.codes(self.repo.check(blocked)), ["security-blocked"])
        pending = self.repo.board_commit(GOOD.replace("security safe", "security pending"))
        self.assertEqual(self.repo.check(pending), [])


class TestCommits(PacketCheckTest):
    def test_code_commit_after_the_head_fails(self):
        board_at = self.repo.board_commit(GOOD)
        self.repo.write("app.py", "v = 3\n")
        later = self.repo.commit("more code")
        self.assertEqual(self.codes(self.repo.check(later)), ["non-board-commit"])
        self.assertEqual(self.repo.check(board_at), [])

    def test_feature_review_allows_later_code(self):
        self.repo.board_commit(GOOD)
        self.repo.write("app.py", "v = 3\n")
        later = self.repo.commit("next story's code")
        problems = packet_check.check(self.repo.path, "board.md", STORY, self.repo.head, later,
                                      self.repo.base, feature_review=True)
        self.assertEqual(problems, [])

    def test_seat_textconv_config_runs_nothing(self):
        marker = Path(self._tmp.name).parent / f"textconv-ran-{Path(self._tmp.name).name}"
        git(self.repo.path, "config", "diff.x.textconv", f"touch {marker}")
        self.repo.write(".gitattributes", "*.md diff=x\n")
        board_at = self.repo.board_commit(GOOD)
        self.assertEqual(self.codes(self.repo.check(board_at)), ["non-board-commit"])
        self.assertFalse(marker.exists())

    def test_board_only_commits_after_the_head_pass(self):
        self.repo.board_commit(GOOD)
        board = (self.repo.path / "board.md").read_text(encoding="utf-8")
        later = self.repo.board_commit("note\n", board=board)
        self.assertEqual(self.repo.check(later), [])

    def test_base_must_be_an_ancestor_of_the_head(self):
        self.repo.write("other.py", "x\n")
        stray = self.repo.commit("stray")
        git(self.repo.path, "reset", "-q", "--hard", self.repo.head)
        entry = GOOD.replace("base {base}", f"base {stray}")
        self.assertEqual(self.codes(self.repo.check(self.repo.board_commit(entry))), ["base-not-ancestor"])

    def test_head_must_be_an_ancestor_of_the_board_commit(self):
        board_at = self.repo.board_commit(GOOD)
        git(self.repo.path, "checkout", "-q", "-b", "side", self.repo.base)
        self.repo.write("app.py", "v = 9\n")
        side = self.repo.commit("side")
        self.assertIn("head-not-ancestor", self.codes(self.repo.check(board_at, head=side)))

    def test_unresolvable_head_is_a_git_error(self):
        board_at = self.repo.board_commit(GOOD)
        with self.assertRaises(packet_check.GitError):
            self.repo.check(board_at, head="0" * 40)


class TestStory(PacketCheckTest):
    def test_unknown_story(self):
        board_at = self.repo.board_commit(GOOD)
        self.assertEqual(self.codes(self.repo.check(board_at, story="STORY-NNNN99")), ["unknown-story"])

    def test_validation_rewritten_since_assignment_fails(self):
        board = BOARD.replace("- [ ] outcome_test.py passes", "- [ ] echo ok")
        problems = self.repo.check(self.repo.board_commit(GOOD, board=board))
        self.assertEqual(self.codes(problems), ["criteria-changed"])
        self.assertIn("validation", problems[0]["message"])

    def test_story_absent_at_assignment_fails(self):
        self.repo.write("board.md", BOARD.replace("STORY-NNNN03", "STORY-NNNN09"))
        elsewhere = self.repo.commit("renamed")
        git(self.repo.path, "reset", "-q", "--hard", self.repo.head)
        board_at = self.repo.board_commit(GOOD)
        self.assertEqual(self.codes(self.repo.check(board_at, assigned_at=elsewhere)),
                         ["criteria-changed"])


class TestUnusualBoardPath(unittest.TestCase):
    def test_board_path_with_spaces_and_non_ascii_counts_as_the_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Without -z, git log quotes a non-ASCII path, and it would never match.
            (Path(tmp) / "plans").mkdir()
            repo = Repo(tmp, board="plans/sprint ü board.md")
            run, packet_check.procguard.run = packet_check.procguard.run, plain_run
            try:
                self.assertEqual(repo.check(repo.board_commit(GOOD)), [])
            finally:
                packet_check.procguard.run = run


class TestMoves(PacketCheckTest):
    def stamped(self, lines, state):
        """The fixture board with its COMMENTS state lines and State value replaced."""
        board = BOARD.replace("- State: Resolved", f"- State: {state}")
        start = board.index("- 2026-11-22T10:00:00Z")
        return board[:start] + "".join(lines) + board[board.rindex(FENCE):]

    def test_state_line_must_match_the_last_state_line(self):
        board = BOARD.replace("- State: Resolved", "- State: Closed")
        self.assertEqual(self.codes(self.repo.check(self.repo.board_commit(GOOD, board=board))),
                         ["state-mismatch"])

    def test_disallowed_move(self):
        board = self.stamped(["- 2026-11-22T10:00:00Z (none) -> New by seat\n",
                              "- 2026-11-22T10:05:00Z New -> Resolved by seat\n"], "Resolved")
        problems = self.repo.check(self.repo.board_commit(GOOD, board=board))
        self.assertEqual(self.codes(problems), ["bad-move"])
        self.assertIn("New -> Resolved", problems[0]["message"])

    def test_broken_trail(self):
        board = self.stamped(["- 2026-11-22T10:00:00Z (none) -> New by seat\n",
                              "- 2026-11-22T10:05:00Z Active -> Resolved by seat\n"], "Resolved")
        self.assertEqual(self.codes(self.repo.check(self.repo.board_commit(GOOD, board=board))),
                         ["broken-trail"])

    def test_closed_needs_an_accept_verdict_for_the_evidence_head(self):
        closing = "- 2026-11-22T12:00:00Z Resolved -> Closed by seat\n"
        board = BOARD.replace("- State: Resolved", "- State: Closed")
        accepted = self.repo.board_commit(GOOD + "- verdict {head} accept\n" + closing, board=board)
        self.assertEqual(self.repo.check(accepted), [])
        rejected = self.repo.board_commit(GOOD + "- verdict {head} reject\n" + closing, board=board)
        self.assertEqual(self.codes(self.repo.check(rejected)), ["bad-move"])
        wrong = self.repo.board_commit(GOOD + "- verdict {base} accept\n" + closing, board=board)
        self.assertEqual(self.codes(self.repo.check(wrong)), ["bad-move"])

    def test_trail_starts_at_the_last_verdict(self):
        # A bad move before the verdict is history; the trail after it starts from Resolved.
        board = self.stamped(["- 2026-11-22T10:00:00Z (none) -> Resolved by seat\n"], "Active")
        entry = GOOD + "- verdict {head} reject\n  - criteria:1 fail still flaky\n" \
                       "- 2026-11-22T12:00:00Z Resolved -> Active by seat\n"
        self.assertEqual(self.repo.check(self.repo.board_commit(entry, board=board)), [])

    def test_no_state_lines_needs_no_state(self):
        unstamped = self.stamped([], "Active")
        self.assertEqual(self.codes(self.repo.check(self.repo.board_commit(GOOD, board=unstamped))),
                         ["state-unstamped"])
        clean = unstamped.replace("- State: Active\n", "")
        self.assertEqual(self.repo.check(self.repo.board_commit(GOOD, board=clean)), [])


class TestVerdict(PacketCheckTest):
    def test_malformed_verdict_header(self):
        entry = GOOD + "- verdict {head} maybe\n"
        self.assertEqual(self.codes(self.repo.check(self.repo.board_commit(entry))), ["bad-header"])

    def test_verdict_items_are_checked(self):
        entry = GOOD + ("- verdict {head} reject\n  - criteria:1 fail flaky\n"
                        "  - security:1 pending settle the list\n  - dod:4 fail none\n  - dod:1 nope\n")
        self.assertEqual(self.codes(self.repo.check(self.repo.board_commit(entry))),
                         ["out-of-range", "bad-item"])


class TestSpawns(PacketCheckTest):
    def test_runs_only_git_and_board_query(self):
        board_at = self.repo.board_commit(GOOD)
        seen, real = [], packet_check.procguard.run

        def record(argv, **kw):
            seen.append(list(argv))
            return real(argv, **kw)

        packet_check.procguard.run = record
        try:
            self.repo.check(board_at)
        finally:
            packet_check.procguard.run = real
        self.assertTrue(seen)
        for argv in seen:
            ok = argv[0] == "git" or argv[:2] == [sys.executable, str(packet_check.BOARD_QUERY)]
            self.assertTrue(ok, argv)


class TestCli(PacketCheckTest):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "packet_check.py"), *args],
                              capture_output=True, text=True)

    def args(self, board_at, head=None):
        return ["--repo", str(self.repo.path), "--board", "board.md", "--story", STORY,
                "--head", head or self.repo.head, "--board-at", board_at,
                "--assigned-at", self.repo.base]

    def test_non_sha_arguments_are_usage_errors(self):
        good = self.repo.board_commit(GOOD)
        for bad in ("HEAD", "abc; echo", "-p", "ABCDEF1"):
            with self.subTest(bad=bad):
                proc = self.run_cli(*self.args(good, head=bad))
                self.assertEqual(proc.returncode, 2)
                if not bad.startswith("-"):  # argparse refuses an option-like value itself
                    self.assertIn("not a commit sha", proc.stderr)

    def test_undecodable_board_is_an_error_not_incomplete(self):
        self.repo.path.joinpath("board.md").write_bytes(
            append_comments(BOARD, GOOD.format(head=self.repo.head, base=self.repo.base))
            .encode("utf-8") + b"\xff\xfe\n")
        bad = self.repo.commit("binary junk")
        self.assertEqual(self.run_cli(*self.args(bad)).returncode, 2)

    def test_exit_codes_and_json(self):
        good = self.repo.board_commit(GOOD)
        proc = self.run_cli(*self.args(good), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"complete": True, "problems": []})
        bad = self.repo.board_commit(GOOD.replace(" security safe", " security blocked"))
        proc = self.run_cli(*self.args(bad), "--json")
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["complete"])
        self.assertEqual(set(payload["problems"][0]), {"line", "code", "message"})
        text = self.run_cli(*self.args(bad))
        self.assertEqual(text.returncode, 1)
        self.assertIn("security-blocked", text.stdout)
        self.assertEqual(self.run_cli(*self.args(good, head="nope")).returncode, 2)
        self.assertEqual(self.run_cli("--repo", str(self.repo.path)).returncode, 2)


if __name__ == "__main__":
    unittest.main()
