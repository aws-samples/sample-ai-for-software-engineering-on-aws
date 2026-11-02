# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Shared parts of the checks: verdicts, result files, settings, git, triage and backlog.

Verdict rules (checks/README.md): the exit status is the verdict (0 PASS, 1 FAIL, 3 BLOCKED, 2 usage or
configuration error); no evidence is not a pass; limits come from limits.json, never from the caller.
"""

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import traceback

PASS, FAIL, USAGE, BLOCKED = "PASS", "FAIL", "USAGE", "BLOCKED"
EXIT = {PASS: 0, FAIL: 1, USAGE: 2, BLOCKED: 3}

CHECKS_DIR = pathlib.Path(__file__).resolve().parent.parent
SAMPLE_DIR = CHECKS_DIR.parent
KNOWLEDGE_DIR = SAMPLE_DIR / "knowledge"
FINDING_ID = re.compile(r"\bF-\d{3}\b")
SOURCE_SUFFIXES = (".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh")


class Usage(Exception):
    """Wrong arguments or configuration: exit 2."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def limits():
    """The limits of the knowledge (each with its source). The caller cannot change them."""
    data = json.loads((CHECKS_DIR / "limits.json").read_text())
    return {k: v["value"] for k, v in data.items() if not k.startswith("_")}


def clean_env(**settings):
    """The environment for tools the checks run: without variables that change test or sanitizer behaviour."""
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("GTEST_") or k.endswith("SAN_OPTIONS") or k.endswith("SAN_SYMBOLIZER_PATH"))}
    env.update(settings)
    return env


def run(cmd, log, cwd=None, env=None):
    """Runs a command, appends its output to the log file, returns its exit status. Never through a pipe."""
    with open(log, "a") as f:
        f.write(f"$ {' '.join(str(c) for c in cmd)}\n")
        f.flush()
        try:
            return subprocess.run(cmd, cwd=cwd, env=env if env is not None else clean_env(), stdout=f,
                                  stderr=subprocess.STDOUT).returncode
        except FileNotFoundError as e:
            f.write(f"{e}\n")
            return 127


def version(cmd):
    """First line of a tool's --version output that names a version, or what went wrong."""
    try:
        out = subprocess.run([cmd, "--version"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return f"{cmd}: not found"
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return next((ln for ln in lines if "version" in ln.lower()), lines[0] if lines else "")


def git(project, *args):
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)


def judged_commit(project, local):
    """The commit a source check judges. A dirty tree is BLOCKED unless --local is given."""
    head = git(project, "rev-parse", "HEAD")
    if head.returncode != 0:
        return None, f"not a git work tree: {project}"
    commit = head.stdout.strip()
    dirty = git(project, "status", "--porcelain", "--untracked-files=normal", "--", ".")
    if dirty.returncode != 0:
        return None, dirty.stderr.strip()
    if dirty.stdout.strip():
        if not local:
            return None, "uncommitted changes in the project; commit them, or use --local for local iteration"
        return commit + "-dirty", None
    return commit, None


def materialize(project, local, dest):
    """A copy of what is judged: the committed tree of HEAD (or, with --local, the tracked and untracked files that
    git does not ignore). Ignored files in the work tree never reach a build."""
    dest = pathlib.Path(dest)
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    if not local:
        archive = dest.parent / f"{dest.name}.tar"
        if git(project, "archive", "--format=tar", "-o", str(archive), "HEAD", "--", ".").returncode != 0:
            raise Usage(f"git archive failed in {project}")
        prefix = git(project, "rev-parse", "--show-prefix").stdout.strip()
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                if m.name.startswith(prefix):
                    m.name = m.name[len(prefix):]
                    if m.name:
                        t.extract(m, dest, filter="data")
        archive.unlink()
        return dest
    files = git(project, "ls-files", "-co", "--exclude-standard", "-z").stdout.split("\0")
    for f in filter(None, files):
        src = pathlib.Path(project) / f
        if src.is_file():
            (dest / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / f)
    return dest


# Ways to hide code from the analysers or the compiler's warnings, other than the suppressions of TR §3.2.
HIDING = re.compile(r"__CPPCHECK__|__clang_analyzer__|__clang_tidy__|clang::suppress|NOLINTBEGIN|NOLINTEND|"
                    r"#\s*pragma\s+(?:GCC|clang)\s+(?:diagnostic|system_header|optimize)|"
                    r"no_sanitize|__SANITIZE_(?:THREAD|ADDRESS)__|__has_feature\s*\(\s*\w+_sanitizer|"
                    r"__(?:t|a|ub|l)san_default_(?:options|suppressions)|"
                    r"__attribute__\s*\(\(\s*optimize")


def hiding_problems(tree, folders=("src", "tests")):
    problems = []
    for folder in folders:
        for path in sorted((pathlib.Path(tree) / folder).rglob("*")):
            if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
                continue
            for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                m = HIDING.search(line)
                if m:
                    problems.append(f"{path.relative_to(tree)}:{n}: {m.group(0)} hides code from the checks "
                                    f"(only the suppressions of TR §3.2 are allowed)")
    return problems


class Result:
    """One check's result: written to <results>/<check>.json, and the exit status is the verdict."""

    def __init__(self, check, results_dir, tier):
        self.check = check
        self.dir = pathlib.Path(results_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log = self.dir / f"{check}.log"
        self.log.write_text("")
        self.data = {"check": check, "verdict": None, "commit": None, "local": False, "tier": tier,
                     "inputs": {}, "details": {}, "reasons": [], "tools": {}, "started": now(), "ended": None}

    def input(self, name, path):
        p = pathlib.Path(path)
        self.data["inputs"][name] = {"path": str(p.resolve()), "sha256": sha256(p) if p.is_file() else None}

    def reason(self, text):
        self.data["reasons"].append(text)

    def finish(self, verdict, summary=None):
        self.data["verdict"] = verdict
        self.data["ended"] = now()
        if summary:
            self.data["summary"] = summary
        (self.dir / f"{self.check}.json").write_text(json.dumps(self.data, indent=2) + "\n")
        print(f"{self.check}: {verdict}" + (f" - {summary}" if summary else ""))
        for r in self.data["reasons"][:20]:
            print(f"  {r}")
        if len(self.data["reasons"]) > 20:
            print(f"  ... {len(self.data['reasons']) - 20} more in {self.dir / (self.check + '.json')}")
        return EXIT[verdict]


def main(check, tier, add_args, body):
    """Common entry point: parses arguments (no option may loosen a limit), runs body(args, result).

    A check that crashes is BLOCKED, with the traceback in its log: it could not judge."""
    parser = Parser(prog=f"checks/{check}.sh")
    parser.add_argument("--results", default="results", help="directory for <check>.json and <check>.log")
    add_args(parser)
    try:
        args = parser.parse_args()
    except Usage as e:
        print(f"{check}: usage error: {e}", file=sys.stderr)
        return EXIT[USAGE]
    result = Result(check, args.results, tier)
    try:
        verdict = body(args, result)
    except Usage as e:
        result.reason(f"configuration error: {e}")
        return result.finish(USAGE)
    except Exception as e:  # noqa: BLE001 - any crash means the check could not judge
        with open(result.log, "a") as f:
            f.write(traceback.format_exc())
        result.reason(f"the check could not judge: {type(e).__name__}: {e}")
        return result.finish(BLOCKED, "check error")
    return result.finish(*verdict) if isinstance(verdict, tuple) else result.finish(verdict)


# ---------------------------------------------------------------------------------------------- knowledge

def backlog_rows(path=None):
    rows = {}
    for line in pathlib.Path(path or KNOWLEDGE_DIR / "findings-backlog.md").read_text().splitlines():
        if line.startswith("| F-"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            loc = re.findall(r"`([^`]+)`", cells[3])
            rows[cells[0]] = {"id": cells[0], "tool": cells[1], "check": cells[2], "location": cells[3],
                              "file": loc[0] if loc else "", "func": loc[1] if len(loc) > 1 else "",
                              "label": cells[5]}
    return rows


def fact_ids():
    ids = set()
    for p in sorted((KNOWLEDGE_DIR / "facts").glob("*.yaml")):
        ids.update(re.findall(r"^- id: (\S+)$", p.read_text(), re.M))
    return ids


def log_fields():
    """Event -> its fields in order, from the table of [VSTATD-IF p.10 §7.1]."""
    text = (KNOWLEDGE_DIR / "vstatd-interface.md").read_text()
    section = text[text.index("**§7.1 Events.**"):text.index("**§7.2")]
    events = {}
    for line in section.splitlines():
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith("`"):
            fields = re.findall(r"`(\w+)`", cells[1])
            for ev in re.findall(r"`([A-Z_]+)`", cells[0]):
                events[ev] = fields
    return events


CITATION = re.compile(r"^\[(?P<doc>VSTATD-IF|CC1-PN|TR)(?: p\.(?P<page>\d+))? §(?P<sec>\d+(?:\.\d+)?)\]$")
DOCS = {"VSTATD-IF": "vstatd-interface.md", "CC1-PN": "cc1-platform-notes.md", "TR": "team-rules.md"}


def section_page(doc, sec):
    """Page of a section (1-based; pages end at <!-- pagebreak -->), or None when the section does not exist."""
    pages = (KNOWLEDGE_DIR / DOCS[doc]).read_text().split("<!-- pagebreak -->")
    pattern = re.compile(rf"(?:^#+ |\*\*)§{re.escape(sec)}(?![.\d])", re.M)
    return next((n for n, page in enumerate(pages, 1) if pattern.search(page)), None)


def citation_problem(cite, docs=("VSTATD-IF", "CC1-PN", "TR")):
    """None when the citation names a section that exists, on the page it gives, in one of docs."""
    m = CITATION.match(str(cite))
    if not m:
        return f"citation {cite!r} is not of the form [VSTATD-IF p.N §x.y] or [CC1-PN §x.y]"
    doc, sec = m.group("doc"), m.group("sec")
    if doc not in docs:
        return f"citation {cite!r}: must cite {' or '.join(docs)}"
    page = section_page(doc, sec)
    if page is None:
        return f"citation {cite!r}: no section §{sec} in {DOCS[doc]}"
    if doc == "VSTATD-IF" and m.group("page") is None:
        return f"citation {cite!r}: VSTATD-IF citations give the page"
    if doc == "VSTATD-IF" and int(m.group("page")) != page:
        return f"citation {cite!r}: §{sec} is on page {page}"
    return None


# ---------------------------------------------------------------------------------------------- triage

DECISIONS = {"fix", "justify", "defer"}
EVIDENCE = {"unit-test", "static-analysis", "build"}
SPEC = ("VSTATD-IF", "CC1-PN")


def load_triage(path, citations=True):
    """The approved triage (TR §4), validated. Returns (triage, problems); problems make a check BLOCKED.

    The approval record <triage>.sha256, written when a person approves the triage, must hold the triage's
    SHA-256: a triage changed after its approval is not approved. With citations=False the citations and fact
    entries are not checked: checks/trace.sh judges those itself."""
    problems = []
    path = pathlib.Path(path)
    try:
        t = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return None, [f"triage {path}: {e}"]
    if not isinstance(t, dict):
        return None, [f"triage {path}: not a JSON object"]
    record = path.with_name(path.name + ".sha256")
    try:
        approved_sha = record.read_text().split()[0]
    except (OSError, IndexError):
        approved_sha = None
    if approved_sha is None:
        problems.append(f"no approval record {record.name} (TR §4.3)")
    elif approved_sha != sha256(path):
        problems.append(f"the triage changed after it was approved ({record.name} does not match)")
    approved = t.get("approved") if isinstance(t.get("approved"), dict) else {}
    if not approved.get("by") or not approved.get("at"):
        problems.append("triage is not approved (approved.by and approved.at, TR §4.3)")
    if not re.fullmatch(r"[0-9a-f]{40}", str(t.get("base", ""))):
        problems.append("triage has no base commit (40 hex digits)")
    rows = backlog_rows()
    batch = {i for i, r in rows.items() if r["label"] == "fix"}
    seen, added = {}, []
    for f in t.get("findings", []) if isinstance(t.get("findings"), list) else []:
        if not isinstance(f, dict) or not FINDING_ID.fullmatch(str(f.get("id", ""))):
            problems.append(f"finding entry without an ID of the form F-nnn: {f!r}")
            continue
        fid = f["id"]
        if fid in seen:
            problems.append(f"{fid}: more than one decision")
        seen[fid] = f
        if f.get("decision") not in DECISIONS:
            problems.append(f"{fid}: decision must be fix, justify or defer")
        for k in ("cites", "facts"):
            if not isinstance(f.get(k, []), list):
                problems.append(f"{fid}: {k} must be a list")
                f[k] = []
        if "added" in f:
            a = f["added"]
            if not isinstance(a, dict) or not a.get("found_by") or fid in rows:
                problems.append(f"{fid}: an added finding names what found it (added.found_by) and is not in the "
                                f"backlog")
            added.append(int(fid[2:]))
        elif fid not in rows:
            problems.append(f"{fid}: not in the backlog and not marked as added under TR §4.4")
        if fid in rows and rows[fid]["label"] != "fix":
            problems.append(f"{fid}: labelled {rows[fid]['label']} in the backlog, not part of the batch")
        if f.get("decision") == "fix":
            if f.get("evidence") not in EVIDENCE:
                problems.append(f"{fid}: a fix gives its evidence: unit-test, static-analysis or build (TR §4.1)")
            if not isinstance(f.get("behaviour"), bool):
                problems.append(f"{fid}: a fix says whether it touches behaviour (true or false)")
        if f.get("decision") == "defer" and not (f.get("reason") and f.get("pick_up_when")):
            problems.append(f"{fid}: a deferral gives a reason and the condition for picking it up (TR §4.1)")
        if citations:
            problems.extend(f"{fid}: {p}" for p in citation_problems(f))
    first_free = max(int(i[2:]) for i in rows) + 1 if rows else 1
    if sorted(added) != list(range(first_free, first_free + len(added))):
        problems.append(f"added findings take the next free IDs from F-{first_free:03d} in turn (TR §4.4): "
                        f"{', '.join(f'F-{n:03d}' for n in sorted(added))}")
    for fid in sorted(batch - set(seen)):
        problems.append(f"{fid}: labelled fix in the backlog but has no decision (TR §4.1)")
    for d in t.get("allowed_log_differences", []):
        if not isinstance(d, dict) or not isinstance(d.get("entry"), dict):
            problems.append(f"allowed log difference must be an object with an entry: {d!r}")
            continue
        f = seen.get(d.get("finding"))
        if not f or f.get("decision") not in ("fix", "justify"):
            problems.append(f"allowed log difference without a fixed or justified finding: {d}")
        if d.get("side") not in ("baseline", "run") or not isinstance(d["entry"].get("ev"), str):
            problems.append(f"allowed log difference needs side (baseline or run) and entry.ev: {d}")
        count, t_ms = d.get("count", 1), d["entry"].get("t_ms", 0)
        if not isinstance(count, int) or isinstance(count, bool) or count < 1 or \
                not isinstance(t_ms, int) or isinstance(t_ms, bool):
            problems.append(f"allowed log difference: count is a positive integer and t_ms an integer: {d}")
    for r in t.get("requirements", []):
        if not isinstance(r, dict) or not r.get("id") or not isinstance(r.get("real_target_only"), bool) or \
                not isinstance(r.get("evidence"), list) or not r["evidence"]:
            problems.append(f"requirement needs id, real_target_only and evidence (check names): {r}")
    return t, problems


def citation_problems(f):
    """What is wrong with a triage entry's citations and fact entries [TR §4.1, §7.2]."""
    problems = []
    if f.get("decision") == "justify" and not f.get("cites"):
        problems.append("a justification cites the specification or platform notes (TR §4.1)")
    if f.get("decision") in ("fix", "justify"):
        spec_only = f.get("decision") == "justify" or f.get("behaviour")
        for cite in f.get("cites", []):
            p = citation_problem(cite, SPEC if spec_only else tuple(DOCS))
            if p:
                problems.append(p)
    if f.get("decision") == "fix" and f.get("behaviour"):
        if not f.get("cites"):
            problems.append("a change that touches behaviour cites a specification page (TR §7.2)")
        if not f.get("facts"):
            problems.append("a change that touches behaviour names its fact entries")
    unknown = sorted(set(map(str, f.get("facts", []))) - fact_ids())
    if unknown:
        problems.append(f"unknown fact entries {', '.join(unknown)}")
    return problems


def decisions(triage):
    return {f["id"]: f for f in triage.get("findings", []) if isinstance(f, dict) and "id" in f}


def id_pattern(fid):
    """The ways a finding ID may be written in code and test names: F-012, F012, F_012; never inside F-0121."""
    n = fid[2:]
    return re.compile(rf"(?<![\w-])F[-_]?{n}(?!\d)")
