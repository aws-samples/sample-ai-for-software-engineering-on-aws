#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""checks/release.sh: every check passed on the final commit [TR §7.1], and no requirement is blocked by its tier.

Pass: a PASS result of every check is in the results directory; the source checks judged the project's HEAD, which
is clean, without --local; every check judged the same approved triage; the build on the bench is the one
checks/build.sh produced and checks/size.sh measured (digests); no input of a result changed after it was judged;
no requirement that the triage marks real-target only [TR §6] has only unit-test or emulation evidence; the two
after-deploy checks judged the same run against the same baseline.
"""

import json
import pathlib
import sys

import common as c

SOURCE_CHECKS = ("build", "static", "unit", "size", "trace")
RUN_CHECKS = ("runtime-limits", "logdiff")
TRIAGE_CHECKS = ("static", "unit", "trace", "logdiff")


def body(args, r):
    lim = c.limits()
    project = pathlib.Path(args.project).resolve()
    results = pathlib.Path(args.results)
    commit, why = c.judged_commit(project, False)
    if why:
        r.reason(why)
        return c.FAIL, "the final commit cannot be judged"
    r.data["commit"] = commit
    triage, problems = c.load_triage(args.triage)
    r.input("triage", args.triage)
    if problems:
        for p in problems:
            r.reason(f"triage: {p}")
        return c.FAIL, "no valid approved triage"
    triage_sha = c.sha256(args.triage)
    checks = SOURCE_CHECKS + RUN_CHECKS
    got = {}
    for name in checks:
        p = results / f"{name}.json"
        try:
            got[name] = json.loads(p.read_text())
        except (OSError, ValueError):
            r.reason(f"{name}: no result")
            continue
        r.input(name, p)
        res = got[name]
        if res.get("verdict") != c.PASS:
            r.reason(f"{name}: {res.get('verdict')}" + (f" - {res['summary']}" if res.get("summary") else ""))
        if res.get("local"):
            r.reason(f"{name}: produced with --local")
        if name in SOURCE_CHECKS and res.get("commit") != commit:
            r.reason(f"{name}: judged {res.get('commit')}, not the final commit {commit}")
        if name in TRIAGE_CHECKS and (res.get("inputs", {}).get("triage") or {}).get("sha256") != triage_sha:
            r.reason(f"{name}: judged against another triage")
        for iname, inp in res.get("inputs", {}).items():
            path = pathlib.Path(inp["path"])
            if inp.get("sha256") and (not path.is_file() or c.sha256(path) != inp["sha256"]):
                r.reason(f"{name}: input {iname} ({path}) changed or went missing after the check")

    digests = {}
    if "build" in got:
        digests["build"] = got["build"].get("details", {}).get("digest")
    if "size" in got:
        digests["size"] = got["size"].get("details", {}).get("digest")
    for name in RUN_CHECKS:
        if name in got:
            digests[f"{name} (installed)"] = got[name].get("details", {}).get("deployed_digest")
            digests[f"{name} (approved)"] = got[name].get("details", {}).get("approved_digest")
    if len(set(digests.values())) > 1:
        r.reason("the build on the bench is not the build that was checked: "
                 + ", ".join(f"{k} {str(v)[:12]}" for k, v in digests.items()))

    same = [k for k in ("run_log", "run_result", "baseline_log", "baseline_result")
            if len({(got[n].get("inputs", {}).get(k) or {}).get("sha256") for n in RUN_CHECKS if n in got}) > 1]
    if same:
        r.reason(f"runtime-limits and logdiff judged different runs or baselines ({', '.join(same)})")

    tiers = {name: res.get("tier") for name, res in got.items()}
    blocked = []
    for req in triage.get("requirements", []):
        if not req.get("real_target_only"):
            continue
        ev = [tiers.get(n) for n in req["evidence"]]
        if "real target" not in ev:
            blocked.append(req["id"])
            r.reason(f"requirement {req['id']} is real-target only (TR §6.1); its evidence is "
                     f"{', '.join(str(t) for t in ev)}: reported as blocked, not passed")

    repair = results / "repair-rounds.json"
    try:
        rounds = json.loads(repair.read_text()) if repair.is_file() else None
    except ValueError:
        rounds = "unreadable"
    r.data["details"].update({"checks": {n: got[n].get("verdict") if n in got else "missing" for n in checks},
                              "tiers": tiers, "digest": digests.get("build"), "blocked_requirements": blocked,
                              "repair_rounds": rounds, "repair_limits": lim["repair_rounds"]})
    if r.data["reasons"]:
        return c.FAIL, f"{len(r.data['reasons'])} problem(s)"
    return c.PASS, f"every check passed on {commit[:12]}; vstatd {digests['build'][:12]}"


def add_args(p):
    p.add_argument("--project", default=".", help="the vstatd project (a git work tree)")
    p.add_argument("--triage", required=True, help="the approved triage (JSON, checks/README.md)")


if __name__ == "__main__":
    sys.exit(c.main("release", "n/a", add_args, body))
