"""Infra and config at code depth: Dockerfile stages, compose services, CI
jobs, package.json scripts and Terraform blocks as symbols, with the calls,
references, dependencies and environment variables between them.

Every expected row below is known from how the files are written, never
read back from the engine."""
import sqlite3
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_symbol_edges import FixtureCase, run  # noqa: E402

import code_kg  # noqa: E402

DOCKERFILE = """\
# build stage
FROM python:3.11-slim AS builder
ARG TIDE_VERSION=1.0
ENV TIDE_DB=/data/tide.db \\
    TIDE_MODE=prod
WORKDIR /app
COPY src/ src/
RUN pip install . && echo "$TIDE_VERSION"

FROM builder AS test
RUN ./scripts/backfill.sh --check

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /app /app
COPY --from=1 /app/report.txt /tmp/
ENV PATH="/app/bin:$PATH"
CMD python3 src/tidelog/cli.py --db "$TIDE_DB"
ENTRYPOINT ["/app/scripts/backfill.sh"]
"""

COMPOSE = """\
services:
  api:
    build:
      context: .
      target: test
    command: ["python3", "src/tidelog/cli.py", "serve"]
    environment:
      - TIDE_DB=/data/tide.db
      - TIDE_TOKEN=${TIDE_TOKEN:-dev}
    depends_on:
      - db
  worker:
    build: .
    command: ./scripts/backfill.sh --loop
    environment:
      TIDE_MODE: worker
      LOG_LEVEL: $LOG_LEVEL
    depends_on:
      db:
        condition: service_healthy
      api:
        condition: service_started
  db:
    image: postgres:16
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]
"""

WORKFLOW = """\
name: ci
on: [push]
env:
  TIDE_MODE: ci
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      TIDE_DB: ./tide.db
    steps:
      - uses: actions/checkout@v4
      - name: unit
        run: |
          npm run lint
          python3 -m tidelog.cli check
          echo "${{ env.TIDE_DB }} $HOME_DIR"
  deploy:
    needs: [test]
    runs-on: ubuntu-latest
    steps:
      - run: ./scripts/backfill.sh
        env:
          DEPLOY_KEY: ${{ secrets.DEPLOY_KEY }}
      - run: make build
  notify:
    needs: deploy
    runs-on: ubuntu-latest
    steps:
      - run: echo done  # ./scripts/backfill.sh in a comment
"""

PACKAGE = """\
{
  "name": "tide-web",
  "scripts": {
    "lint": "node tools/lint.js",
    "prebuild": "npm run lint",
    "build": "tsc -p . && ./scripts/backfill.sh",
    "test": "node --test"
  }
}
"""

MAKEFILE = "build:\n\t./scripts/backfill.sh\n\nall:\n\t@$(MAKE) build\n"

TF_VARS = """\
variable "region" {
  default = "us-east-2"
}
variable "cidr" {}
"""

TF_MAIN = """\
provider "aws" {
  region = var.region
}
locals {
  name = "tide-${var.region}"
  tags = { app = local.name }
}
module "net" {
  source = "./modules/net"
  cidr   = var.cidr
}
data "aws_ami" "base" {
  most_recent = true
}
resource "aws_instance" "app" {
  ami       = data.aws_ami.base.id
  subnet_id = module.net.subnet_id
  tags      = local.tags
  # var.unused in a comment
  user_data = "echo local.name is not a ref"
  depends_on = [aws_s3_bucket.logs]
}
resource "aws_s3_bucket" "logs" {
  bucket = "${local.name}-logs"
}
output "ip" {
  value = aws_instance.app.private_ip
}
"""

TF_NET = """\
variable "cidr" {}
resource "aws_subnet" "this" {
  cidr_block = var.cidr
}
output "subnet_id" {
  value = aws_subnet.this.id
}
"""

TF_EXAMPLE = """\
module "root" {
  source = "../../.."
}
output "ip" {
  value = module.root.subnet_id
}
"""

DEPLOY_SH = """\
#!/usr/bin/env bash
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
bash "$HERE/helper.sh" --x
python3 "$ROOT/src/tidelog/cli.py" run
"${HERE}/helper.sh"
echo "$HERE/helper.sh is not run"
# "$HERE/helper.sh" in a comment
TOP=$(git rev-parse --show-toplevel)
"$TOP/scripts/backfill.sh"
NEXT="$HERE/helper.sh"; X="$TOP/scripts/backfill.sh"
FILES=(
  "tools/helper.sh"
  scripts/backfill.sh
)
node "$(cd "$(dirname "$0")" && pwd)/lint.js" "$OUT"
H="$(cd "$(dirname "$0")" && pwd)"; RUNS="${RUNS:-2}"
bash "$H/helper.sh"
EXTRA="--a b --c d" \\
  bash "$H/helper.sh" "x"
"$NEXT" --again
"""

SETTINGS = 'import os\nDB = os.environ.get("TIDE_DB", "tide.db")\n'

INFRA_FILES = {
    "Dockerfile": DOCKERFILE,
    "docker-compose.yml": COMPOSE,
    ".github/workflows/ci.yml": WORKFLOW,
    "package.json": PACKAGE,
    "Makefile": MAKEFILE,
    "tools/lint.js": "console.log('lint')\n",
    "infra/variables.tf": TF_VARS,
    "infra/main.tf": TF_MAIN,
    "infra/modules/net/main.tf": TF_NET,
    "infra/examples/demo/main.tf": TF_EXAMPLE,
    "main.tf": TF_NET,
    "tools/deploy.sh": DEPLOY_SH,
    "tools/helper.sh": ":\n",
    "src/tidelog/settings.py": SETTINGS,
}

D, C, W, P = ("Dockerfile", "docker-compose.yml", ".github/workflows/ci.yml",
              "package.json")
BACKFILL = "scripts/backfill.sh::<module>"
CLI = "src/tidelog/cli.py::<module>"
I, V, N = "infra/main.tf", "infra/variables.tf", "infra/modules/net/main.tf"


class InfraCase(FixtureCase):
    def setUp(self):
        super().setUp()
        for rel, text in INFRA_FILES.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        rc, _, err = run("ingest", str(self.repo))
        self.assertEqual(rc, 0, err)

    def query(self, sql, *params):
        con = sqlite3.connect(code_kg.db_path(self.repo))
        got = sorted(con.execute(sql, params))
        con.close()
        return got

    def edges(self, fid):
        return self.query(
            "SELECT src, ifnull(dst, ''), kind, line, status FROM"
            " symbol_edges WHERE"
            " src_file=? AND status IN ('resolved','external')", fid)

    def data(self, fid):
        return self.query(
            "SELECT src, kind, node, line, status FROM data_edges WHERE"
            " src_file=? AND node_kind='env'", fid)

    def symbols(self, fid):
        return self.query(
            "SELECT qualname, kind, line_start, line_end FROM symbols"
            " WHERE file_id=?", fid)


class TestDockerfile(InfraCase):
    def test_stages_are_symbols(self):
        self.assertEqual(self.symbols(D), [
            ("stage.2", "stage", 13, 19),
            ("stage.builder", "stage", 2, 9),
            ("stage.test", "stage", 10, 12)])

    def test_stage_edges(self):
        b, t, s2 = (f"{D}::stage.builder", f"{D}::stage.test",
                    f"{D}::stage.2")
        self.assertEqual(self.edges(D), sorted([
            (b, "", "extends", 2, "external"),
            (t, b, "extends", 10, "resolved"),
            (t, BACKFILL, "call", 11, "resolved"),
            (s2, "", "extends", 13, "external"),
            (s2, b, "ref", 15, "resolved"),
            (s2, t, "ref", 16, "resolved"),
            (s2, CLI, "call", 18, "resolved"),
            (s2, BACKFILL, "call", 19, "resolved")]))

    def test_env_and_arg(self):
        b, s2 = f"{D}::stage.builder", f"{D}::stage.2"
        self.assertEqual(self.data(D), sorted([
            (b, "write", "TIDE_VERSION", 3, "resolved"),
            (b, "write", "TIDE_DB", 4, "resolved"),
            (b, "write", "TIDE_MODE", 5, "resolved"),
            (b, "read", "TIDE_VERSION", 8, "resolved"),
            (s2, "write", "PATH", 17, "resolved"),
            (s2, "read", "PATH", 17, "weak"),
            (s2, "read", "TIDE_DB", 18, "weak")]))


class TestCompose(InfraCase):
    def test_services_are_symbols(self):
        self.assertEqual(self.symbols(C), [
            ("services.api", "service", 2, 11),
            ("services.db", "service", 23, 26),
            ("services.worker", "service", 12, 22)])

    def test_service_edges(self):
        api, worker, db = (f"{C}::services.api", f"{C}::services.worker",
                           f"{C}::services.db")
        self.assertEqual(self.edges(C), sorted([
            (api, f"{D}::stage.test", "ref", 5, "resolved"),
            (api, CLI, "call", 6, "resolved"),
            (api, db, "depends-on", 11, "resolved"),
            (worker, f"{D}::stage.2", "ref", 13, "resolved"),
            (worker, BACKFILL, "call", 14, "resolved"),
            (worker, db, "depends-on", 19, "resolved"),
            (worker, api, "depends-on", 21, "resolved")]))

    def test_environment_and_interpolation(self):
        api, worker = f"{C}::services.api", f"{C}::services.worker"
        self.assertEqual(self.data(C), sorted([
            (api, "write", "TIDE_DB", 8, "resolved"),
            (api, "write", "TIDE_TOKEN", 9, "resolved"),
            (api, "read", "TIDE_TOKEN", 9, "resolved"),
            (worker, "write", "TIDE_MODE", 16, "resolved"),
            (worker, "write", "LOG_LEVEL", 17, "resolved"),
            (worker, "read", "LOG_LEVEL", 17, "resolved")]))


class TestWorkflow(InfraCase):
    def test_jobs_are_symbols(self):
        self.assertEqual(self.symbols(W), [
            ("jobs.deploy", "job", 17, 24),
            ("jobs.notify", "job", 25, 29),
            ("jobs.test", "job", 6, 16)])

    def test_job_edges(self):
        test, deploy, notify = (f"{W}::jobs.test", f"{W}::jobs.deploy",
                                f"{W}::jobs.notify")
        self.assertEqual(self.edges(W), sorted([
            (test, f"{P}::scripts.lint", "call", 14, "resolved"),
            (test, CLI, "call", 15, "resolved"),
            (deploy, test, "depends-on", 18, "resolved"),
            (deploy, BACKFILL, "call", 21, "resolved"),
            (deploy, "Makefile::build", "call", 24, "resolved"),
            (notify, deploy, "depends-on", 26, "resolved")]))

    def test_env_at_every_level(self):
        test, deploy = f"{W}::jobs.test", f"{W}::jobs.deploy"
        self.assertEqual(self.data(W), sorted([
            (f"{W}::<module>", "write", "TIDE_MODE", 4, "resolved"),
            (test, "write", "TIDE_DB", 9, "resolved"),
            (test, "read", "TIDE_DB", 16, "resolved"),
            (test, "read", "HOME_DIR", 16, "weak"),
            (deploy, "write", "DEPLOY_KEY", 23, "resolved")]))


class TestPackageScripts(InfraCase):
    def test_scripts_are_symbols(self):
        self.assertEqual(self.symbols(P), [
            ("scripts.build", "script", 6, 6),
            ("scripts.lint", "script", 4, 4),
            ("scripts.prebuild", "script", 5, 5),
            ("scripts.test", "script", 7, 7)])

    def test_script_edges(self):
        s = f"{P}::scripts."
        self.assertEqual(self.edges(P), sorted([
            (s + "lint", "tools/lint.js::<module>", "call", 4, "resolved"),
            (s + "prebuild", s + "lint", "call", 5, "resolved"),
            (s + "build", s + "prebuild", "call", 6, "resolved"),
            (s + "build", BACKFILL, "call", 6, "resolved")]))


class TestMakefile(InfraCase):
    def test_a_recipe_calls_a_script(self):
        self.assertEqual(self.edges("Makefile"), [
            ("Makefile::all", "Makefile::build", "call", 5, "resolved"),
            ("Makefile::build", BACKFILL, "call", 2, "resolved")])


class TestTerraform(InfraCase):
    def test_references_between_blocks(self):
        app, logs = (f"{I}::resource.aws_instance.app",
                     f"{I}::resource.aws_s3_bucket.logs")
        self.assertEqual(self.edges(I), sorted([
            (f"{I}::provider.aws", f"{V}::variable.region", "ref", 2,
             "resolved"),
            (f"{I}::locals", f"{V}::variable.region", "ref", 5, "resolved"),
            (f"{I}::module.net", f"{V}::variable.cidr", "ref", 10,
             "resolved"),
            (f"{I}::module.net", f"{N}::variable.cidr", "ref", 10,
             "resolved"),
            (app, f"{I}::data.aws_ami.base", "ref", 16, "resolved"),
            (app, f"{I}::module.net", "ref", 17, "resolved"),
            (app, f"{N}::output.subnet_id", "ref", 17, "resolved"),
            (app, f"{I}::locals", "ref", 18, "resolved"),
            (app, logs, "depends-on", 21, "resolved"),
            (logs, f"{I}::locals", "ref", 24, "resolved"),
            (f"{I}::output.ip", app, "ref", 27, "resolved")]))
        self.assertEqual(self.edges(N), sorted([
            (f"{N}::resource.aws_subnet.this", f"{N}::variable.cidr", "ref",
             3, "resolved"),
            (f"{N}::output.subnet_id", f"{N}::resource.aws_subnet.this",
             "ref", 6, "resolved")]))


class TestTerraformUpwardSource(InfraCase):
    def test_a_module_sourced_from_the_repo_root(self):
        E = "infra/examples/demo/main.tf"
        self.assertEqual(self.edges(E), sorted([
            (f"{E}::output.ip", f"{E}::module.root", "ref", 5, "resolved"),
            (f"{E}::output.ip", "main.tf::output.subnet_id", "ref", 5,
             "resolved")]))


class TestScriptFolderVariables(InfraCase):
    def test_a_script_runs_its_siblings_through_a_folder_variable(self):
        m = "tools/deploy.sh::<module>"
        self.assertEqual(self.edges("tools/deploy.sh"), sorted([
            (m, "tools/helper.sh::<module>", "call", 4, "resolved"),
            (m, CLI, "call", 5, "resolved"),
            (m, "tools/helper.sh::<module>", "call", 6, "resolved"),
            (m, BACKFILL, "call", 10, "resolved"),
            (m, "tools/lint.js::<module>", "call", 16, "resolved"),
            (m, "tools/helper.sh::<module>", "call", 18, "resolved"),
            (m, "tools/helper.sh::<module>", "call", 20, "resolved"),
            (m, "tools/helper.sh::<module>", "call", 21, "resolved")]))


class TestOneEnvNode(InfraCase):
    def test_touches_env_spans_every_format(self):
        got = self.json("touches", "env:TIDE_DB", "--limit", "0")["rows"]
        self.assertEqual(sorted((r["src"], r["access"], r["line"])
                                for r in got), sorted([
            (f"{D}::stage.builder", "write", 4),
            (f"{D}::stage.2", "read", 18),
            (f"{C}::services.api", "write", 8),
            (f"{W}::jobs.test", "write", 9),
            (f"{W}::jobs.test", "read", 16),
            ("src/tidelog/settings.py::<module>", "read", 2)]))

    def test_callers_of_a_script_span_every_format(self):
        got = self.json("callers", BACKFILL, "--limit", "0")["edges"]
        self.assertEqual(sorted(r["src"] for r in got), sorted([
            f"{D}::stage.test", f"{D}::stage.2", f"{C}::services.worker",
            f"{W}::jobs.deploy", f"{P}::scripts.build", "Makefile::build",
            "tools/deploy.sh::<module>"]))


class TestInfraHostileInput(unittest.TestCase):
    def test_infra_scanners_stay_fast_on_adversarial_text(self):
        import shutil
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="ckg-infra-redos-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        n = 100_000
        deep = "".join("  " * i + "k:\n" for i in range(400))
        files = {
            "Dockerfile": "FROM a AS b\n" + "ENV " + "A=" * (n // 2) + "\n"
            + "COPY --from=" + "x" * n + "\n" + "RUN " + "$" * n + "\n"
            + "ARG" + " " * n + "x\n" + "\\\n" * 20000,
            "docker-compose.yml": "services:\n  a:\n    environment:\n"
            + "      - " + "A" * n + "\n" + "    command: " + "${" * n
            + "\n" + deep + "    depends_on: [" + "a," * (n // 2) + "\n",
            ".github/workflows/ci.yml": "jobs:\n  a:\n    needs: ["
            + " " * n + "\n    steps:\n      - run: |\n"
            + "          " + "${{ env." * (n // 8) + "\n"
            + ("- " * 1999 + "\n") * 25
            + "x: " + '"' * n + "\n",
            "package.json": '{"scripts": {"a": "' + "npm run " * (n // 8)
            + '"}}\n',
            "h.sh": 'x="' + " " * n + '"\n'
            + ('H="$(cd "$(dirname "$0")' + "/.." * 300 + '" && pwd)"\n'
               + '"$H/' + "a/" * 400 + 'x.sh"\n') * 200
            + 'A=(' + " (" * 5000 + "\n" + '"' + '$(' * 5000 + '"\n'
            + ('X=$(cd ' + "$(cd " * 150 + "\n") * 100,
            # Many depends_on spans, closed and not, against many refs.
            "dep.tf": "depends_on = []\n" * 6000 + "var.a\n" * 16000
            + "depends_on = [\n" * 20000,
            "main.tf": "resource \"a_b\" \"c\" {\n  x = " + "var." * n
            + "\n  depends_on = [" + "a_b.c " * (n // 6) + "\n}\n"
            + "locals {\n" + "  " + "a" * n + " =\n}\n",
        }
        for rel, text in files.items():
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        start = time.time()
        rc, _, err = run("ingest", str(tmp))
        self.assertEqual(rc, 0, err)
        self.assertLess(time.time() - start, 5.0)


if __name__ == "__main__":
    unittest.main()
