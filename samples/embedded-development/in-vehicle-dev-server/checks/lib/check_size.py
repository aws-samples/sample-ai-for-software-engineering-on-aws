#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""checks/size.sh: the stripped size of the cross-built `vstatd` within [CC1-PN §3].

Judges the artifact that checks/build.sh produced for the same commit (its digest must still match); without a
passing build of this commit there is nothing to judge (BLOCKED).
"""

import json
import pathlib
import sys

import common as c


def body(args, r):
    lim = c.limits()
    project = pathlib.Path(args.project).resolve()
    commit, why = c.judged_commit(project, args.local)
    if why:
        r.reason(why)
        return c.BLOCKED, "cannot judge the tree"
    r.data["commit"], r.data["local"] = commit, args.local
    build_json = pathlib.Path(args.results) / "build.json"
    try:
        build = json.loads(build_json.read_text())
    except (OSError, ValueError):
        r.reason("no result of checks/build.sh in the results directory")
        return c.BLOCKED, "run checks/build.sh first"
    r.input("build_result", build_json)
    if build.get("verdict") != c.PASS or build.get("commit") != commit:
        r.reason(f"build result is {build.get('verdict')} for {build.get('commit')}, not PASS for {commit}")
        return c.BLOCKED, "no passing build of this commit"
    artifact = pathlib.Path(build["details"]["artifact"])
    if not artifact.is_file() or c.sha256(artifact) != build["details"]["digest"]:
        r.reason(f"{artifact} is missing or no longer has the digest checks/build.sh recorded")
        return c.BLOCKED, "artifact changed"
    r.input("artifact", artifact)
    size, limit = artifact.stat().st_size, lim["stripped_size_bytes"]
    r.data["details"].update({"size_bytes": size, "limit_bytes": limit, "digest": build["details"]["digest"]})
    if size > limit:
        r.reason(f"stripped vstatd is {size} bytes, over the limit of {limit} bytes (CC1-PN §3)")
        return c.FAIL, f"{size} > {limit} bytes"
    return c.PASS, f"{size} of {limit} bytes ({100 * size / limit:.0f} %)"


def add_args(p):
    p.add_argument("--project", default=".", help="the vstatd project (a git work tree)")
    p.add_argument("--local", action="store_true", help="judge a dirty tree; release.sh rejects the result")


if __name__ == "__main__":
    sys.exit(c.main("size", "n/a", add_args, body))
