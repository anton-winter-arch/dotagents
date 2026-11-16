"""Symbol-level edges: what calls, references, decorates and extends what.

The fixture is the docs-and-code tree in the markdown-kg skill, with one
module added at test time, so every expected edge below is known from how
the tree is written, never read back from the engine."""
import ast
import contextlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))
import code_kg  # noqa: E402

LINKED = code_kg.SIBLING_CLI.parent.parent / "tests" / "linked-fixture-repo"

SYNC = '''"""Refresh a station from the lines it is handed."""
from tidelog.station import Station


def refresh(station, lines):
    return station.read_day(lines)


def make(name):
    return Station(name)


def logged(fn):
    return fn


class LoggingStation(Station):
    @logged
    def summary(self):
        return "log " + super().summary()
'''

R, C, P, S, Y = ("src/tidelog/reader.py", "src/tidelog/cli.py",
                 "src/tidelog/report.py", "src/tidelog/station.py",
                 "src/tidelog/sync.py")


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = code_kg.main(list(argv))
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else (0 if e.code is None
                                                         else 1)
            if isinstance(e.code, str):
                err.write(e.code)
    return rc, out.getvalue(), err.getvalue()


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ckg-sym-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        shutil.copytree(LINKED, self.repo)
        (self.repo / Y).write_text(SYNC, encoding="utf-8")
        rc, _, err = run("ingest", str(self.repo))
        self.assertEqual(rc, 0, err)

    def json(self, *argv: str):
        rc, out, err = run(argv[0], str(self.repo), *argv[1:], "--json")
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def resolved(self, rows):
        return sorted((r["src"], r["dst"], r["kind"], r["line"])
                      for r in rows if r["status"] == "resolved")


class TestStaticEdges(FixtureCase):
    def test_every_resolved_edge_in_the_tree(self):
        con = sqlite3.connect(code_kg.db_path(self.repo))
        got = sorted(con.execute(
            "SELECT src, dst, kind, line FROM symbol_edges"
            " WHERE status='resolved'"))
        con.close()
        self.assertEqual(got, sorted([
            (f"{C}::<module>", f"{R}::read_day", "import", 4),
            (f"{C}::<module>", f"{P}::high_low", "import", 5),
            (f"{C}::<module>", f"{C}::main", "call", 17),
            (f"{C}::main", f"{R}::read_day", "call", 11),
            (f"{C}::main", f"{P}::high_low", "call", 12),
            (f"{P}::<module>", f"{R}::read_day", "import", 2),
            (f"{P}::high_low", f"{R}::read_day", "call", 6),
            (f"{R}::read_day", f"{R}::parse_line", "ref", 16),
            (f"{Y}::<module>", f"{S}::Station", "import", 2),
            (f"{Y}::make", f"{S}::Station", "call", 10),
            (f"{Y}::LoggingStation", f"{S}::Station", "extends", 17),
            (f"{Y}::LoggingStation.summary", f"{Y}::logged", "decorated-by",
             18),
            (f"{Y}::LoggingStation.summary", f"{S}::Station.summary", "call",
             20),
        ]))

    def test_callers_of_a_function(self):
        got = self.json("callers", f"{R}::read_day")
        self.assertEqual(got["symbol"], f"{R}::read_day")
        self.assertEqual(self.resolved(got["edges"]), sorted([
            (f"{C}::<module>", f"{R}::read_day", "import", 4),
            (f"{C}::main", f"{R}::read_day", "call", 11),
            (f"{P}::<module>", f"{R}::read_day", "import", 2),
            (f"{P}::high_low", f"{R}::read_day", "call", 6)]))
        # A method call on a parameter is not evidence for a module function.
        self.assertEqual(got["name_matched"], [])

    def test_an_unknown_receiver_is_only_a_name_match(self):
        got = self.json("callers", f"{S}::Station.read_day")
        self.assertEqual(self.resolved(got["edges"]), [])
        self.assertEqual(
            [(r["src"], r["target"], r["status"], r["line"])
             for r in got["name_matched"]],
            [(f"{Y}::refresh", "station.read_day", "weak", 6)])

    def test_callees_keep_every_call_site(self):
        got = self.json("callees", f"{C}::main")
        by_status = {}
        for r in got["edges"]:
            by_status.setdefault(r["status"], []).append(r["target"])
        self.assertEqual(sorted(by_status["resolved"]),
                         ["high_low", "read_day"])
        self.assertEqual(sorted(by_status["external"]),
                         ["len", "open", "print", "print"])
        self.assertEqual(by_status["unresolved"], ["fh.readlines"])
        # Resolved rows rank first.
        self.assertEqual({r["status"] for r in got["edges"][:2]},
                         {"resolved"})

    def test_a_name_resolves_when_it_is_unique(self):
        self.assertEqual(self.json("callers", "high_low")["symbol"],
                         f"{P}::high_low")
        rc, _, err = run("callers", str(self.repo), "read_day")
        self.assertNotEqual(rc, 0)
        self.assertIn(f"{R}::read_day", err)
        self.assertIn(f"{S}::Station.read_day", err)

    def test_depth_follows_resolved_edges(self):
        got = self.json("callees", f"{C}::main", "--depth", "2")
        deep = {(r["dst"], r["depth"]) for r in got["edges"]
                if r["status"] == "resolved"}
        self.assertIn((f"{R}::parse_line", 2), deep)
        self.assertIn((f"{R}::read_day", 1), deep)

    def test_extends_both_ways(self):
        up = self.json("extends", f"{Y}::LoggingStation")
        self.assertEqual([r["dst"] for r in up["bases"]], [f"{S}::Station"])
        down = self.json("extends", f"{S}::Station")
        self.assertEqual([r["src"] for r in down["subclasses"]],
                         [f"{Y}::LoggingStation"])

    def test_prose_and_limit(self):
        rc, out, _ = run("callees", str(self.repo), f"{C}::main")
        self.assertEqual(rc, 0)
        self.assertIn("read_day", out)
        got = self.json("callees", f"{C}::main", "--limit", "1")
        self.assertEqual(len(got["edges"]), 1)
        self.assertTrue(got["status"].startswith("TRUNCATED 1 of"))


TYPED = '''from tidelog.station import Station


def tally(lines):
    st = Station("x")
    return st.read_day(lines)


def count(st: Station):
    return st.summary()


def twice(lines, other):
    st = Station("x")
    st = other
    return st.read_day(lines)
'''


class TestReceiverTypes(FixtureCase):
    """A local bound once to a repo class, or a parameter annotated with
    one, gives its method calls a known receiver."""

    def setUp(self):
        super().setUp()
        (self.repo / "src/tidelog/typed.py").write_text(TYPED,
                                                        encoding="utf-8")
        run("ingest", str(self.repo))

    def calls(self, sym):
        return sorted((r["target"], r["dst"], r["status"])
                      for r in self.json("callees", sym)["edges"]
                      if r["kind"] == "call")

    def test_constructed_local(self):
        T = "src/tidelog/typed.py"
        self.assertIn(("st.read_day", f"{S}::Station.read_day", "resolved"),
                      self.calls(f"{T}::tally"))

    def test_annotated_parameter(self):
        T = "src/tidelog/typed.py"
        self.assertIn(("st.summary", f"{S}::Station.summary", "resolved"),
                      self.calls(f"{T}::count"))

    def test_a_rebound_local_stays_a_name_match(self):
        T = "src/tidelog/typed.py"
        self.assertIn(("st.read_day", None, "weak"), self.calls(f"{T}::twice"))


STORE = '''"""Store readings."""
import os
import sqlite3

DB_PATH = "tides.db"
SEEN = []


def save(rows):
    con = sqlite3.connect(DB_PATH)
    con.executemany("INSERT INTO readings(time, height) VALUES (?, ?)", rows)
    SEEN.append(len(rows))


def load():
    con = sqlite3.connect(DB_PATH)
    return con.execute("SELECT time, height FROM readings").fetchall()


def home():
    return os.environ.get("TIDELOG_HOME", "~")


def dump(path, rows):
    with open(path, "w") as fh:
        fh.write(str(rows))


def nightly():
    dump("night.txt", load())
'''
D = "src/tidelog/store.py"


class TestDataFlow(FixtureCase):
    """Reads and writes of globals, tables, files and environment
    variables, and what a parameter carries into a callee."""

    def setUp(self):
        super().setUp()
        (self.repo / D).write_text(STORE, encoding="utf-8")
        run("ingest", str(self.repo))

    def direct(self, sym):
        got = self.json("flow", f"{D}::{sym}", "--depth", "0")
        return sorted((r["access"], r["node_kind"], r["node"], r["line"])
                      for r in got["rows"])

    def test_direct_reads_and_writes(self):
        self.assertEqual(self.direct("save"), sorted([
            ("read", "global", f"{D}::DB_PATH", 10),
            ("open", "file", "tides.db", 10),
            ("write", "table", "readings", 11),
            ("write", "global", f"{D}::SEEN", 12)]))
        self.assertEqual(self.direct("load"), sorted([
            ("read", "global", f"{D}::DB_PATH", 16),
            ("open", "file", "tides.db", 16),
            ("read", "table", "readings", 17)]))
        self.assertEqual(self.direct("home"),
                         [("read", "env", "TIDELOG_HOME", 21)])
        # A file named by a parameter is reported as that parameter.
        self.assertEqual(self.direct("dump"),
                         [("write", "file", "param:path", 25)])

    def test_flow_through_calls(self):
        got = self.json("flow", f"{D}::nightly", "--depth", "2")
        rows = {(r["access"], r["node_kind"], r["node"], r["hops"])
                for r in got["rows"]}
        # The literal nightly passes becomes the file dump writes.
        self.assertIn(("write", "file", "night.txt", 1), rows)
        self.assertIn(("read", "table", "readings", 1), rows)
        self.assertNotIn(("write", "file", "param:path", 1), rows)
        for r in got["rows"]:
            self.assertEqual(r["provenance"], "inferred")
            self.assertTrue(r["via"])

    def test_flow_stops_at_its_row_budget(self):
        old = code_kg.FLOW_ROWS_MAX
        self.addCleanup(setattr, code_kg, "FLOW_ROWS_MAX", old)
        code_kg.FLOW_ROWS_MAX = 1
        got = self.json("flow", f"{D}::nightly", "--depth", "2")
        self.assertTrue(got["status"].startswith("TRUNCATED"))

    def test_who_touches_a_node(self):
        got = self.json("touches", "table:readings")
        self.assertEqual(sorted((r["src"], r["access"]) for r in got["rows"]),
                         [(f"{D}::load", "read"), (f"{D}::save", "write")])
        env = self.json("touches", "env:TIDELOG_HOME")
        self.assertEqual([r["src"] for r in env["rows"]], [f"{D}::home"])


HELPER = '''def assist():
    return 1
'''
HELPER_TEST = '''import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import helper  # noqa: E402
from helper import assist  # noqa: E402


def test_it():
    return helper.assist() + assist()
'''
SHAPES = '''def a():
    return 1


def b():
    return 2


TABLE = {"a": a, "b": b}


def run(name):
    return TABLE[name]()


class Engine:
    def go(self):
        return 1


class Car:
    def __init__(self, engine: "Engine"):
        self.engine = engine
        self.spare = Engine()

    def start(self):
        return self.engine.go() + self.spare.go()
'''


class TestHarderShapes(FixtureCase):
    """Imports through a path the file adds to sys.path, dispatch through
    a dict of functions, and attributes `__init__` sets."""

    def setUp(self):
        super().setUp()
        tools = self.repo / "tools"
        (tools / "scripts").mkdir(parents=True)
        (tools / "tests").mkdir()
        (tools / "scripts" / "helper.py").write_text(HELPER, encoding="utf-8")
        (tools / "tests" / "test_helper.py").write_text(HELPER_TEST,
                                                       encoding="utf-8")
        (self.repo / "src/tidelog/shapes.py").write_text(SHAPES,
                                                         encoding="utf-8")
        run("ingest", str(self.repo))

    def calls(self, sym):
        return sorted((r["target"], r["dst"], r["status"], tuple(
            r["candidates"])) for r in self.json("callees", sym)["edges"]
            if r["kind"] == "call")

    def test_a_path_added_to_sys_path_resolves_imports(self):
        got = self.calls("tools/tests/test_helper.py::test_it")
        h = "tools/scripts/helper.py::assist"
        self.assertIn(("helper.assist", h, "resolved", ()), got)
        self.assertIn(("assist", h, "resolved", ()), got)

    def test_dict_dispatch_lists_its_candidates(self):
        T = "src/tidelog/shapes.py"
        self.assertIn(("TABLE[name]", None, "ambiguous",
                       (f"{T}::a", f"{T}::b")), self.calls(f"{T}::run"))

    def test_attributes_set_in_init_type_their_receiver(self):
        T = "src/tidelog/shapes.py"
        got = self.calls(f"{T}::Car.start")
        self.assertIn(("self.engine.go", f"{T}::Engine.go", "resolved", ()),
                      got)
        self.assertIn(("self.spare.go", f"{T}::Engine.go", "resolved", ()),
                      got)


PATHS = '''from tidelog.reader import read_day
from tidelog.report import high_low


def pick(flag, lines):
    return high_low(lines) if flag else read_day(lines)


def guard(lines):
    if not lines:
        return read_day(lines)
    return None


def hidden():
    return 1


def dispatch(name):
    return globals()[name]()


class Box:
    def __init__(self):
        self.full = False


def boxed():
    return Box()
'''
PATHS_TEST = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tidelog.paths import boxed, dispatch, guard, pick  # noqa: E402


class PathsTest(unittest.TestCase):
    def test_pick(self):
        self.assertEqual(pick(True, ["01:00,1.0", "02:00,2.0"]),
                         {"low": "01:00", "high": "02:00"})

    def test_guard(self):
        self.assertIsNone(guard(["x"]))

    def test_dispatch(self):
        self.assertEqual(dispatch("hidden"), 1)

    def test_boxed(self):
        self.assertFalse(boxed().full)
'''
PA = "src/tidelog/paths.py"


class TestObserved(FixtureCase):
    """Calls seen while the repo's own tests run, each static edge given
    one of four states, and the calls the static graph missed."""

    def setUp(self):
        super().setUp()
        (self.repo / PA).write_text(PATHS, encoding="utf-8")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_paths.py").write_text(PATHS_TEST,
                                                           encoding="utf-8")
        cfg = code_kg.config_path(self.repo)
        cfg.parent.mkdir(exist_ok=True)
        cfg.write_text(json.dumps({"test_command": (
            f"{sys.executable} -m unittest discover -s tests")}),
            encoding="utf-8")
        run("ingest", str(self.repo))
        rc, out, err = run("coverage", str(self.repo), "run", "--yes",
                           "--calls", "--json")
        self.assertEqual(rc, 0, err)
        self.result = json.loads(out)

    def states(self, sym):
        got = self.json("observed", sym)
        return {(r["dst"], r["line"]): r["state"] for r in got["edges"]}, got

    def test_the_run_is_recorded(self):
        trace = self.result["trace"]
        self.assertEqual(self.result["exit_code"], 0)
        self.assertGreaterEqual(trace["processes"], 1)
        self.assertGreater(trace["calls"], 0)

    def test_four_states(self):
        st, got = self.states(f"{PA}::pick")
        self.assertEqual(st[(f"{P}::high_low", 6)], "observed")
        self.assertEqual(st[(f"{R}::read_day", 6)], "line_ran_not_called")
        self.assertEqual(got["entries"], 1)
        self.assertFalse(got["run"]["stale"])
        st, _ = self.states(f"{PA}::guard")
        self.assertEqual(st[(f"{R}::read_day", 11)], "line_never_ran")
        st, _ = self.states(f"{C}::main")
        self.assertEqual(set(st.values()), {"caller_never_ran"})
        # A function passed to map is a static ref, and it ran.
        st, _ = self.states(f"{R}::read_day")
        self.assertEqual(st[(f"{R}::parse_line", 16)], "observed")

    def test_the_gap_is_what_static_reading_missed(self):
        got = self.json("observed", "--gap")
        self.assertEqual([(r["src"], r["dst"]) for r in got["gap"]],
                         [(f"{PA}::dispatch", f"{PA}::hidden")])
        self.assertGreater(got["observed_pairs"], 1)

    def test_observed_adds_use_and_never_removes_it(self):
        got = self.json("dead", "--symbols", "--limit", "0")
        self.assertIn(f"{PA}::hidden", got["observed_live"])
        self.assertNotIn(f"{PA}::hidden", got["no_resolved_use"])
        self.assertIn("src/tidelog/legacy_export.py::export",
                      got["no_resolved_use"])

    def test_lines_fold_into_coverage(self):
        got = self.json("coverage", "report")
        files = {f["file"]: f for f in got["files"]}
        self.assertGreater(files[PA]["lines_hit"], 0)
        self.assertLess(files[PA]["lines_hit"], files[PA]["lines_seen"])

    def test_the_tracer_leaves_nothing_behind(self):
        self.assertFalse((code_kg.kg_dir(self.repo) / "trace").exists())

    def test_consent_names_the_tracer(self):
        rc, _, err = run("coverage", str(self.repo), "run", "--calls")
        self.assertNotEqual(rc, 0)
        self.assertIn("-m unittest discover -s tests", err)
        self.assertIn("call tracer", err)

    def test_hostile_trace_files_are_skipped(self):
        out = self.tmp / "out"
        out.mkdir()
        good = {"lines": {str(self.repo.resolve() / PA): [6]},
                "entries": [], "calls": []}
        for i, text in enumerate([
                "[1, 2]", "{" * 100000, json.dumps({"entries": [[1, 2]]}),
                json.dumps({"calls": [["x", "y", "z", 1, "f", 1]]}),
                json.dumps({"lines": {str(self.repo.resolve() / PA):
                                      [10 ** 9, -1, "6"]}}),
                json.dumps(good)]):
            (out / f"trace-{i}.json").write_text(text, encoding="utf-8")
        got = code_kg.trace_ingest(self.repo, out, {"command": "x",
                                                    "exit_code": 0})
        self.assertEqual(got["processes"], 3)
        self.assertEqual(got["files_with_lines"], 1)


class TestSymbolLiveness(FixtureCase):
    def test_dead_by_symbol(self):
        got = self.json("dead", "--symbols")
        self.assertEqual(sorted(got["no_resolved_use"]), sorted([
            "src/tidelog/legacy_export.py::export",
            f"{Y}::refresh", f"{Y}::make", f"{Y}::LoggingStation",
            f"{Y}::LoggingStation.summary"]))
        self.assertEqual(got["name_matched_only"], [f"{S}::Station.read_day"])
        self.assertIn("not proof", got["note"])

    def test_dead_without_the_flag_is_as_before(self):
        self.assertNotIn("no_resolved_use", self.json("dead"))


class TestAgainstAnIndependentWalk(unittest.TestCase):
    """On a real tree, every function a separate name-based walk finds
    unreferenced must be in the engine's no-resolved-use list."""

    def test_the_engine_on_its_own_source(self):
        tmp = Path(tempfile.mkdtemp(prefix="ckg-self-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = tmp / "repo"
        (repo / "scripts").mkdir(parents=True)
        src = (SKILL_DIR / "scripts" / "code_kg.py").read_text()
        # One function nothing calls, appended so the check has a positive.
        src += "\n\ndef _never_called_probe():\n    return 0\n"
        (repo / "scripts" / "code_kg.py").write_text(src, encoding="utf-8")
        rc, _, err = run("ingest", str(repo))
        self.assertEqual(rc, 0, err)
        rc, out, err = run("dead", str(repo), "--symbols", "--limit", "0",
                           "--json")
        self.assertEqual(rc, 0, err)
        flagged = set(json.loads(out)["no_resolved_use"])
        tree = ast.parse(src)
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value,
                                                               str):
                used.add(node.value)
        unreferenced = {f"scripts/code_kg.py::{n.name}" for n in tree.body
                        if isinstance(n, ast.FunctionDef)
                        and n.name not in used}
        self.assertIn("scripts/code_kg.py::_never_called_probe", unreferenced)
        self.assertLessEqual(unreferenced, flagged)


LANG_FILES = {
    "web/lib.ts": '''export function greet(name: string): string {
  return "hi " + name;
}
export class Base {}
''',
    "web/util.ts": '''export function shout(s: string) {
  return s.toUpperCase();
}
''',
    "web/widget.ts": '''export default class Widget {
  render() { return "w"; }
}
''',
    "web/app.ts": '''import { greet, Base } from "./lib";
import * as util from "./util";
import Widget from "./widget";

export class App extends Base {
  run(): string {
    const s = greet("x");
    util.shout(s);
    return new Widget().render();
  }
}

export function boot() {
  const handlers = [greet];
  return handlers;
}
// greet("comment") should not count
const msg = "greet(not a call)";
''',
    "web/view.tsx": '''import Widget from "./widget";
export function View() {
  return <Widget />;
}
''',
    "tools/common.sh": '''log() {
  echo "$1"
}
''',
    "tools/build.sh": '''#!/bin/bash
source "$(dirname "$0")/common.sh"
setup() {
  log "setting up"
  export BUILD_MODE=fast
}
# setup should not count here
main() {
  setup && log "done"
  echo "$HOME_DIR"
}
main "$@"
''',
    "db/schema.sql": '''CREATE TABLE readings (id INTEGER PRIMARY KEY,
  station_id INTEGER REFERENCES stations(id));
CREATE TABLE stations (id INTEGER PRIMARY KEY);
-- SELECT * FROM ghosts;
CREATE VIEW high AS
  SELECT * FROM readings JOIN stations ON 1;
INSERT INTO stations VALUES (1);
CREATE INDEX readings_station ON readings(station_id);
''',
    "web/index.html": '''<link rel="stylesheet" href="style.css">
<div class="card wide" id="main" onclick="boot()">x</div>
<style>
  .wide { width: 100%; }
</style>
''',
    "web/style.css": '''.card { color: var(--accent); }
#main { --accent: red; }
.unused { margin: 0; }
''',
}


class TestOtherLanguages(FixtureCase):
    """Call, reference and data edges for JS/TS, bash, SQL, HTML and CSS,
    each expected row known from the files above."""

    def setUp(self):
        super().setUp()
        for rel, text in LANG_FILES.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        run("ingest", str(self.repo))

    def edges(self, prefix):
        con = sqlite3.connect(code_kg.db_path(self.repo))
        got = sorted(con.execute(
            "SELECT src, dst, kind, line FROM symbol_edges WHERE"
            " status='resolved' AND src_file LIKE ?", (prefix + "%",)))
        con.close()
        return got

    def data(self, prefix):
        con = sqlite3.connect(code_kg.db_path(self.repo))
        got = sorted(con.execute(
            "SELECT src, kind, node_kind, node, line, status FROM data_edges"
            " WHERE src_file LIKE ? AND kind != 'param'", (prefix + "%",)))
        con.close()
        return got

    def test_typescript(self):
        A, L, U, W, V = ("web/app.ts", "web/lib.ts", "web/util.ts",
                         "web/widget.ts", "web/view.tsx")
        self.assertEqual(self.edges("web/app.ts"), sorted([
            (f"{A}::<module>", f"{L}::greet", "import", 1),
            (f"{A}::<module>", f"{L}::Base", "import", 1),
            (f"{A}::<module>", f"{W}::Widget", "import", 3),
            (f"{A}::App", f"{L}::Base", "extends", 5),
            (f"{A}::App", f"{L}::greet", "call", 7),
            (f"{A}::App", f"{U}::shout", "call", 8),
            (f"{A}::App", f"{W}::Widget", "call", 9),
            (f"{A}::boot", f"{L}::greet", "ref", 14)]))
        self.assertEqual(self.edges("web/view.tsx"), sorted([
            (f"{V}::<module>", f"{W}::Widget", "import", 1),
            (f"{V}::View", f"{W}::Widget", "call", 3)]))

    def test_bash(self):
        B, M = "tools/build.sh", "tools/common.sh"
        self.assertEqual(self.edges("tools/build.sh"), sorted([
            (f"{B}::setup", f"{M}::log", "call", 4),
            (f"{B}::main", f"{B}::setup", "call", 9),
            (f"{B}::main", f"{M}::log", "call", 9),
            (f"{B}::<module>", f"{B}::main", "call", 12)]))
        self.assertEqual(self.data("tools/build.sh"), sorted([
            (f"{B}::setup", "write", "env", "BUILD_MODE", 5, "resolved"),
            (f"{B}::main", "read", "env", "HOME_DIR", 10, "weak")]))

    def test_sql(self):
        S = "db/schema.sql"
        self.assertEqual(self.edges("db/"), sorted([
            (f"{S}::readings", f"{S}::stations", "ref", 2),
            (f"{S}::high", f"{S}::readings", "ref", 6),
            (f"{S}::high", f"{S}::stations", "ref", 6),
            (f"{S}::readings_station", f"{S}::readings", "ref", 8)]))
        self.assertEqual(self.data("db/"), sorted([
            (f"{S}::high", "read", "table", "readings", 6, "resolved"),
            (f"{S}::high", "read", "table", "stations", 6, "resolved"),
            (f"{S}::<module>", "write", "table", "stations", 7,
             "resolved")]))

    def test_html_and_css_meet_on_class_names(self):
        got = self.json("touches", "css-class:card")
        self.assertEqual(sorted((r["src"], r["access"]) for r in got["rows"]),
                         [("web/index.html::<module>", "use"),
                          ("web/style.css::<module>", "define")])
        wide = self.json("touches", "css-class:wide")["rows"]
        self.assertEqual(sorted((r["access"], r["line"]) for r in wide),
                         [("define", 4), ("use", 2)])
        unused = self.json("touches", "css-class:unused")["rows"]
        self.assertEqual([r["access"] for r in unused], ["define"])
        var = self.json("touches", "css-var:accent")["rows"]
        self.assertEqual(sorted(r["access"] for r in var), ["define", "use"])

    def test_template_literal_holes_are_code(self):
        text = "const c = `x ${f(`y ${g({a: 1})}`)} z(`;\n// h()\n'i()'"
        out = code_kg._blank(text, ("//",), ("/*", "*/"), "'\"`", "`",
                             code_kg.JS_HOLES)
        self.assertIn("f(", out)
        self.assertIn("g({a: 1})", out)
        for gone in ("x ", "y ", " z(", "h()", "i()"):
            self.assertNotIn(gone, out)
        self.assertEqual(len(out), len(text))

    def test_bash_strings_hide_words_but_keep_substitutions(self):
        text = 'ok "a (no b)"; x="$(log y) $# ${#arr[@]}"; run # c\n'
        out = code_kg._blank(text, ("#",), None, "'\"", '"',
                             code_kg.BASH_HOLES, comment_after_space=True)
        self.assertNotIn("no b", out)
        self.assertIn("log y", out)
        self.assertIn("run", out)
        self.assertNotIn(" c", out.split("run")[1])

    def test_bash_quoted_heredoc_and_env_prefix(self):
        (self.repo / "tools/t.sh").write_text(
            "check() { :; }\n"
            "check deny 'python3 - <<EOF'\n"
            "check pass 'grep x'\n"
            'ROOT="$HOME/x" check nudge "y"\n'
            "cat <<EOF\ncheck inside heredoc\nEOF\n"
            "check after\n"
            "x=$(check sub)\n"
            "check pass 'git commit -m \"a\n\nb > c\"'\n"
            "check last\n"
            'case "$x" in a) check arm;; *) check other;; esac\n',
            encoding="utf-8")
        run("ingest", str(self.repo))
        got = [ln for _, _, kind, ln in self.edges("tools/t.sh")
               if kind == "call"]
        self.assertEqual(got, [2, 3, 4, 8, 9, 10, 13, 14, 14])

    def test_an_inline_handler_names_a_script_function(self):
        con = sqlite3.connect(code_kg.db_path(self.repo))
        got = con.execute(
            "SELECT target, status, candidates FROM symbol_edges WHERE"
            " src='web/index.html::<module>' AND kind='call'").fetchall()
        con.close()
        self.assertEqual(got, [("boot", "weak", "web/app.ts::boot")])


class TestHostileInput(unittest.TestCase):
    def test_deep_nesting_does_not_stop_the_ingest(self):
        tmp = Path(tempfile.mkdtemp(prefix="ckg-deep-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        # Parses, but a recursive walk of 20,000 nested BinOps overflows.
        (tmp / "deep.py").write_text("x = " + " + ".join(["a"] * 20000)
                                     + "\n", encoding="utf-8")
        (tmp / "ok.py").write_text("def f():\n    return g()\n\n\n"
                                   "def g():\n    return 1\n",
                                   encoding="utf-8")
        rc, _, err = run("ingest", str(tmp))
        self.assertEqual(rc, 0, err)
        rc, out, _ = run("callees", str(tmp), "ok.py::f", "--json")
        self.assertEqual(json.loads(out)["edges"][0]["dst"], "ok.py::g")

    def test_scanners_stay_fast_on_adversarial_text(self):
        """Shapes that made the line scanners backtrack exponentially or
        quadratically, each about 100 KB, through a real ingest."""
        import time
        tmp = Path(tempfile.mkdtemp(prefix="ckg-redos-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        n = 100_000
        files = {
            "a.sh": "x=" + "$aaa" * 40 + ";\n" + "declare " + "a" * n + "\n"
            + "source a" + " " * n + "b\n",
            # Blank and comment-line tails, and values that re-enter the
            # assignment chain.
            "d.sh": "f() { :; }\n" + "# c\n" * 20000 + "\n" * 20000,
            "e.sh": ("a=" + "{a=" * 130 + " \n") * 300,
            "f.sql": "SELECT * FROM " + ", ".join(
                f"t{i}" for i in range(1800)) + ";\n",
            "b.ts": "import" + " " * n + "x\n" + "a" + " " * n + "x\n"
            + "class " + "a" * n + "\n" + "class a " * (n // 8) + "\n"
            + "a<" + " " * n + "\n",
            "c.html": "<script>" * (n // 8) + "\n",
        }
        for rel, text in files.items():
            (tmp / rel).write_text(text, encoding="utf-8")
        start = time.time()
        rc, _, err = run("ingest", str(tmp))
        self.assertEqual(rc, 0, err)
        self.assertLess(time.time() - start, 5.0)

    def test_sql_scan_is_linear_on_whitespace(self):
        import time
        sql = "UPDATE" + " " * 20000 + "x"
        start = time.time()
        code_kg.sql_tables(sql)
        code_kg.sql_tables("CREATE TABLE" + " " * 20000 + "x")
        code_kg.sql_tables("DROP TABLE" + " " * 20000 + "x")
        self.assertLess(time.time() - start, 1.0)
        self.assertEqual(code_kg.sql_tables(
            "CREATE TABLE IF NOT EXISTS t(a); UPDATE OR IGNORE u SET a=1;"
            " DELETE FROM v; SELECT * FROM w JOIN z ON 1"),
            [("read", "w"), ("read", "z"), ("write", "t"), ("write", "u"),
             ("write", "v")])


class TestIndexRevision(unittest.TestCase):
    def test_revision_is_bumped_for_the_new_table(self):
        self.assertEqual(code_kg.INDEX_REV, 2)


if __name__ == "__main__":
    unittest.main()
