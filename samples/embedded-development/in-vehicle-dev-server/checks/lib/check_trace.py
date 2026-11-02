#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""checks/trace.sh: every change and justification of the batch is traced [TR §4.1, §7.2].

Judges the commits from the triage's base commit to HEAD. Pass: every commit cites at least one finding (F-nnn) that
the approved triage fixes or justifies; a commit for a fix that touches behaviour also cites one of that finding's
fact entries; every fix has at least one commit; every justification and every behaviour-related fix in the triage
cites a section of VSTATD-IF or CC1-PN that exists, and its fact entries exist. A batch with no commit is BLOCKED.
"""

import pathlib
import re
import sys

import common as c


def body(args, r):
    project = pathlib.Path(args.project).resolve()
    commit, why = c.judged_commit(project, args.local)
    if why:
        r.reason(why)
        return c.BLOCKED, "cannot judge the tree"
    r.data["commit"], r.data["local"] = commit, args.local
    triage, problems = c.load_triage(args.triage, citations=False)
    r.input("triage", args.triage)
    if problems:
        for p in problems:
            r.reason(f"triage: {p}")
        return c.BLOCKED, "no valid approved triage"
    base = triage["base"]
    if c.git(project, "merge-base", "--is-ancestor", base, "HEAD").returncode != 0:
        r.reason(f"base commit {base} of the triage is not an ancestor of HEAD")
        return c.BLOCKED, "unknown base commit"
    decided = c.decisions(triage)
    known = set(c.backlog_rows()) | {fid for fid, f in decided.items() if f.get("added")}

    for fid, f in sorted(decided.items()):
        for p in c.citation_problems(f):
            r.reason(f"triage {fid}: {p}")

    revs = c.git(project, "rev-list", "--reverse", f"{base}..HEAD").stdout.split()
    if not revs:
        r.reason("no commit between the triage's base and HEAD")
        return c.BLOCKED, "nothing to trace"
    traced, rows = {}, []
    for rev in revs:
        msg = c.git(project, "log", "-1", "--format=%B", rev).stdout
        subject = msg.strip().splitlines()[0] if msg.strip() else ""
        ids = sorted(set(c.FINDING_ID.findall(msg)))
        files = c.git(project, "diff-tree", "--no-commit-id", "--name-only", "-r", rev).stdout.split()
        rows.append({"commit": rev[:12], "subject": subject, "findings": ids, "files": len(files)})
        if not ids:
            r.reason(f"{rev[:12]} {subject!r}: cites no finding")
            continue
        for fid in ids:
            if fid not in known:
                r.reason(f"{rev[:12]}: cites {fid}, which is neither in the backlog nor added in the triage")
                continue
            f = decided.get(fid)
            if not f or f["decision"] not in ("fix", "justify"):
                r.reason(f"{rev[:12]}: cites {fid}, which the approved triage does not fix or justify "
                         f"({f['decision'] if f else 'not in the batch'})")
                continue
            traced.setdefault(fid, []).append(rev[:12])
            if f["decision"] == "fix" and f.get("behaviour"):
                facts = [x for x in f.get("facts", []) if re.search(rf"\b{re.escape(x)}\b", msg)]
                if not facts:
                    r.reason(f"{rev[:12]}: {fid} touches behaviour; the commit cites none of its fact entries "
                             f"({', '.join(f.get('facts', []))})")
    if args.local:
        dirty = c.git(project, "status", "--porcelain").stdout.strip()
        if dirty:
            r.reason("uncommitted changes are not traced: commit them")
    for fid, f in sorted(decided.items()):
        if f["decision"] == "fix" and fid not in traced:
            r.reason(f"{fid}: triaged as fix, but no commit cites it")
    r.data["details"].update({"base": base, "commits": rows, "traced": traced})
    if r.data["reasons"]:
        return c.FAIL, f"{len(r.data['reasons'])} problem(s) in {len(revs)} commit(s)"
    return c.PASS, f"{len(revs)} commit(s), {len(traced)} finding(s) traced"


def add_args(p):
    p.add_argument("--project", default=".", help="the vstatd project (a git work tree)")
    p.add_argument("--triage", required=True, help="the approved triage (JSON, checks/README.md)")
    p.add_argument("--local", action="store_true", help="judge a dirty tree; release.sh rejects the result")


if __name__ == "__main__":
    sys.exit(c.main("trace", "n/a", add_args, body))
