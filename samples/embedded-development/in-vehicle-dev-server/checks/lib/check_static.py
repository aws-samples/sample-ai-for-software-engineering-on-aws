#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""checks/static.sh: static analysis with the team's settings [TR §3], judged against the backlog and the triage.

Runs cppcheck 2.13 and clang-tidy 18 on a fresh cross configuration of the committed tree, with the settings of
TR §3.1. The settings are the check's own copy (lib/clang-tidy.yaml), so a change to the project's .clang-tidy does
not change the verdict. Pass: both analysers completed on every file; no finding outside the backlog; a finding
triaged as fix is gone; a finding that is gone was triaged as fix or justify; every inline suppression has a form of
TR §3.2, names a justified backlog finding of the same check and sits in that finding's function, once; and no code
is hidden from the analysers in another way.
"""

import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys

import common as c

LIB = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("match_backlog", LIB / "match_backlog.py")
mb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mb)

CPPCHECK_ARGS = ["--std=c++17", "--library=posix", "--enable=warning,style,performance,portability",
                 "--inline-suppr", "--quiet", "--template={file}:{line}:{column}: {severity}: {id}: {message}"]
SUPPRESSION = re.compile(r"cppcheck-suppress|NOLINT")
CPPCHECK_SUPPRESS = re.compile(r"//\s*cppcheck-suppress (?P<check>[\w-]+) ; (?P<id>F-\d{3}) justified\s*$")
NOLINT = re.compile(r"//\s*NOLINT\((?P<check>[\w.-]+)\) (?P<id>F-\d{3}) justified\s*$")


def suppression_problems(tree, decided, rows):
    """Problems with the inline suppressions under src/, and the justified findings they name (ID -> places)."""
    problems, named, cache = [], {}, {}
    tree = pathlib.Path(tree)
    for path in sorted((tree / "src").rglob("*")):
        if path.suffix not in c.SOURCE_SUFFIXES or not path.is_file():
            continue
        lines = path.read_text(errors="replace").splitlines()
        for n, line in enumerate(lines, 1):
            if not SUPPRESSION.search(line):
                continue
            rel = str(path.relative_to(tree))
            where = f"{rel}:{n}"
            m = CPPCHECK_SUPPRESS.search(line) or NOLINT.search(line)
            if not m:
                problems.append(f"{where}: suppression not in a form of TR §3.2: {line.strip()}")
                continue
            fid, check = m.group("id"), m.group("check")
            # A cppcheck suppression alone on its line applies to the next line.
            target = n + 1 if m.re is CPPCHECK_SUPPRESS and line.strip().startswith("//") else n
            func = mb.locate(str(path), min(target, len(lines)), cache)
            row = rows.get(fid)
            if decided.get(fid, {}).get("decision") != "justify":
                problems.append(f"{where}: suppression names {fid}, which the approved triage does not justify")
            elif not row:
                problems.append(f"{where}: suppression names {fid}, which is not an analyser finding of the backlog")
            elif row["check"] != check:
                problems.append(f"{where}: suppression of {check} names {fid}, a {row['check']} finding")
            elif (rel, func) != (row["file"], row["func"]):
                problems.append(f"{where}: suppression names {fid}, which is in {row['file']} › {row['func']}, not "
                                f"in {rel} › {func}")
            else:
                named.setdefault(fid, []).append(where)
    for fid, places in named.items():
        if len(places) > 1:
            problems.append(f"{fid}: suppressed in {len(places)} places ({', '.join(places)}); a justification "
                            f"covers its one finding")
    return problems, named


def judge(findings, rows, decided, named):
    """Reasons for FAIL, and the per-finding table, from the analyser findings, the backlog and the triage."""
    reasons, hits, table = [], {}, []
    for tool, check, path, func, msg, lineno, source in findings:
        match = [row for row in rows.values()
                 if (row["tool"], row["check"], row["file"], row["func"], row["msg"]) == (tool, check, path, func, msg)
                 and (row["note"] is None or row["note"] in source)]
        if len(match) == 1:
            hits.setdefault(match[0]["id"], []).append(f"{path}:{lineno}")
        else:
            reasons.append(f"new finding, not in the backlog: {tool} {check} {path}:{lineno} ({func}): {msg}")
            table.append({"id": None, "tool": tool, "check": check, "where": f"{path}:{lineno}", "status": "new"})
    for fid, row in rows.items():
        n = len(hits.get(fid, []))
        decision = decided.get(fid, {}).get("decision") or row["label"]
        status = "reported" if n == 1 else ("gone" if n == 0 else f"reported {n} times")
        table.append({"id": fid, "check": row["check"], "decision": decision, "status": status,
                      "suppressed_at": named.get(fid, [])})
        if n > 1:
            reasons.append(f"{fid}: reported {n} times ({', '.join(hits[fid])}); the copies are new findings")
        elif n == 1 and decision == "fix":
            reasons.append(f"{fid}: triaged as fix but still reported at {hits[fid][0]}")
        elif n == 0 and decision not in ("fix", "justify"):
            reasons.append(f"{fid}: no longer reported, but triaged as {decision}; a change outside the batch removed it")
        elif n == 0 and decision == "justify" and fid not in named:
            reasons.append(f"{fid}: justified, gone, but no suppression names it; something else changed")
    for fid, f in decided.items():
        if f.get("added"):
            table.append({"id": fid, "check": f["added"].get("tool", ""), "decision": f["decision"],
                          "status": "added under TR §4.4 (found by " + f["added"]["found_by"] + ")"})
    return reasons, table


def body(args, r):
    lim = c.limits()
    project = pathlib.Path(args.project).resolve()
    commit, why = c.judged_commit(project, args.local)
    if why:
        r.reason(why)
        return c.BLOCKED, "cannot judge the tree"
    r.data["commit"], r.data["local"] = commit, args.local
    triage, problems = c.load_triage(args.triage)
    r.input("triage", args.triage)
    if problems:
        for p in problems:
            r.reason(f"triage: {p}")
        return c.BLOCKED, "no valid approved triage"
    decided = c.decisions(triage)

    r.data["tools"] = {"cppcheck": c.version("cppcheck"), "clang-tidy": c.version("clang-tidy")}
    if not r.data["tools"]["cppcheck"].startswith(lim["cppcheck_version"]) or \
            lim["clang_tidy_version"] not in r.data["tools"]["clang-tidy"]:
        r.reason(f"analyser versions {r.data['tools']} are not those of TR §3.1")
        return c.BLOCKED, "wrong analyser versions"

    work = pathlib.Path(args.results).resolve() / "work" / "static"
    shutil.rmtree(work, ignore_errors=True)
    tree = c.materialize(project, args.local, work / "tree")
    build, out = work / "build", work / "analysis"
    out.mkdir(parents=True)
    toolchain = tree / "cmake" / "cc1-aarch64.cmake"
    if c.run(["cmake", "-S", tree, "-B", build, "-G", "Ninja", f"-DCMAKE_TOOLCHAIN_FILE={toolchain}"], r.log) != 0:
        r.reason("cmake configuration failed (see checks/build.sh)")
        return c.BLOCKED, "no cross configuration to analyse"
    db = build / "compile_commands.json"
    if not db.is_file():
        r.reason("the configuration writes no compile_commands.json (CMAKE_EXPORT_COMPILE_COMMANDS)")
        return c.FAIL, "nothing to analyse"
    files = sorted({e["file"] for e in json.loads(db.read_text())})
    if not files:
        r.reason("compile_commands.json lists no file")
        return c.FAIL, "nothing to analyse"

    env = c.clean_env()
    with open(out / "cppcheck.txt", "w") as err, open(r.log, "a") as log:
        rc_cpp = subprocess.run(["cppcheck", *CPPCHECK_ARGS, f"--project={db}", "-j", "4"], stdout=log,
                                stderr=err, env=env).returncode
    with open(out / "clang-tidy.txt", "w") as o, open(out / "clang-tidy.err", "w") as e:
        rc_tidy = subprocess.run(["clang-tidy", f"--config-file={LIB / 'clang-tidy.yaml'}", "-p", build, "--quiet",
                                  *files], stdout=o, stderr=e, env=env).returncode
    r.data["details"]["exit_status"] = {"cppcheck": rc_cpp, "clang-tidy": rc_tidy}
    tidy_err = (out / "clang-tidy.err").read_text(errors="replace")
    if rc_cpp != 0:
        r.reason(f"cppcheck exited with {rc_cpp}")
        return c.BLOCKED, "cppcheck did not complete"
    if rc_tidy != 0 or "Error while processing" in tidy_err:
        errors = [ln for ln in (out / "clang-tidy.txt").read_text(errors="replace").splitlines() + tidy_err.splitlines()
                  if "error:" in ln or "Error while processing" in ln]
        for ln in errors[:10]:
            r.reason(ln.replace(str(tree) + "/", ""))
        r.reason(f"clang-tidy exited with {rc_tidy}: a file it could not compile was not analysed")
        return c.BLOCKED, "clang-tidy did not complete"

    rows = {row["id"]: row for row in mb.read_backlog(c.KNOWLEDGE_DIR / "findings-backlog.md")}
    findings = mb.read_findings(out, {})
    for p in c.hiding_problems(tree, ("src",)):
        r.reason(p)
    sup_problems, named = suppression_problems(tree, decided, c.backlog_rows())
    for p in sup_problems:
        r.reason(p)
    reasons, table = judge(findings, rows, decided, named)
    for x in reasons:
        r.reason(x)
    r.data["details"]["findings"] = table
    r.data["details"]["counts"] = {"reported": len(findings), "backlog_rows": len(rows),
                                   "new": sum(1 for t in table if t["status"] == "new")}
    if r.data["reasons"]:
        return c.FAIL, f"{len(r.data['reasons'])} problem(s)"
    return c.PASS, f"{len(findings)} findings, all in the backlog and consistent with the triage"


def add_args(p):
    p.add_argument("--project", default=".", help="the vstatd project (a git work tree)")
    p.add_argument("--triage", required=True, help="the approved triage (JSON, checks/README.md)")
    p.add_argument("--local", action="store_true", help="judge a dirty tree; release.sh rejects the result")


if __name__ == "__main__":
    sys.exit(c.main("static", "n/a", add_args, body))
