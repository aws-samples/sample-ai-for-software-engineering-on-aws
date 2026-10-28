#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Checks an install that the hw plugin was composed into, against the same install before composition.

    python3 tests/check_compose.py <install-before> <install-after> <harness-dir>     # for example ... .kiro

Checks the stages, their edges, scopes and order; where each step is spliced into a core stage; and that, without
the plugin's blocks, every core stage reads exactly as before. Exits 0 when every check passes, 1 otherwise, and
prints one line per check.
"""

import difflib
import json
import pathlib
import re
import sys

PHASES = ["initialization", "ideation", "inception", "construction", "operation"]
CORE_SCOPES = ["enterprise", "feature", "mvp", "poc", "bugfix", "refactor", "security-patch", "classic", "workshop",
               "express"]
NO_OPERATION = {"classic", "mvp", "poc"}
NEW_STAGES = {
    "hw-verification-planning": ("inception", ["requirements-analysis"]),
    "hw-simulation-verification": ("construction", ["build-and-test", "hw-verification-planning"]),
    "hw-bench-deployment": ("operation", ["hw-simulation-verification", "build-and-test", "hw-verification-planning"]),
    "hw-evidence-signoff": ("operation", ["hw-bench-deployment", "hw-simulation-verification", "build-and-test",
                                          "hw-verification-planning"]),
}
PRODUCES = {"hw-verification-planning": "hw-verification-plan", "hw-simulation-verification": "hw-simulation-results",
            "hw-bench-deployment": "hw-bench-results", "hw-evidence-signoff": "hw-evidence-page"}
# Core stage -> (what comes before, the hardware step, what comes after) for each step spliced into it.
FRAGMENTS = {
    "inception/requirements-analysis.md": [("### Step 1:", "Step 1a (hw)", "### Step 2:"),
                                           ("Step 1a (hw)", "Step 1b (hw)", "### Step 2:"),
                                           ("### Step 10:", "Step 10a (hw)", "### Step 11:")],
    "construction/code-generation.md": [("### Step 2:", "Step 2a (hw)", "### Step 3:"),
                                        ("### Step 3:", "Step 3a (hw)", "### Step 4:"),
                                        ("### Step 5:", "Step 5a (hw)", "### Step 6:")],
    "construction/build-and-test.md": [("### Step 1:", "Step 1a (hw)", "### Step 2:"),
                                       ("### Step 2:", "Step 2a (hw)", "### Step 3-7:"),
                                       ("### Step 9:", "Step 9a (hw)", "### Step 10:")],
    "construction/nfr-requirements.md": [("## Steps", "Before you start (hw)", "### Step 1:")],
    "construction/nfr-design.md": [("## Steps", "Before you start (hw)", "### Step 1:")],
}
# Core stage -> the lines the plugin's contributions add to its frontmatter (adds.consumes), as ndiff shows them.
CONSUMES = {rel: ["+   - artifact: hw-verification-plan", "+     required: false"]
            for rel in ("construction/code-generation.md", "construction/build-and-test.md",
                        "construction/nfr-requirements.md", "construction/nfr-design.md")}
BLOCK = re.compile(r"\n*<!-- plugin:hw:[^>]*-->.*?<!-- /plugin:hw:[^>]*-->\n*", re.S)

failures = 0


def check(ok, text):
    global failures
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'} {text}")


def key(stage):
    return PHASES.index(stage["phase"]), [int(x) for x in stage["number"].split(".")]


def split(text):
    """Frontmatter lines and body of a stage file."""
    _, front, body = text.split("---\n", 2)
    return front.splitlines(), body


def normal(text):
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def main():
    before, after, harness = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
    data = after / harness / "tools" / "data"
    graph = json.loads((data / "stage-graph.json").read_text())
    grid = json.loads((data / "scope-grid.json").read_text())
    by_slug = {s["slug"]: s for s in graph}
    order = [s["slug"] for s in graph]
    check(order == [s["slug"] for s in sorted(graph, key=key)], "the graph lists the stages in phase and number order")

    for slug, (phase, edges) in NEW_STAGES.items():
        node = by_slug.get(slug)
        check(node is not None and node["phase"] == phase and node.get("plugin") == "hw",
              f"{slug} is a stage of {phase}, owned by hw")
        if node is None:
            continue
        check(sorted(node.get("requires_stage", [])) == sorted(edges), f"{slug} requires {', '.join(edges)}")
        for dep in edges:
            check(dep in by_slug and order.index(dep) < order.index(slug), f"{slug} runs after {dep}")
        check(node.get("produces") == [PRODUCES[slug]], f"{slug} produces {PRODUCES[slug]}")
        for scope in CORE_SCOPES + ["infra"]:
            want = "SKIP" if scope == "infra" or (phase == "operation" and scope in NO_OPERATION) else "EXECUTE"
            got = grid.get(scope, {}).get("stages", {}).get(slug)
            check(got == want, f"{slug} is {want} in scope {scope}")
    hw_nodes = {s["slug"] for s in graph if s.get("plugin") == "hw"}
    check(hw_nodes == set(NEW_STAGES), "the plugin owns exactly the four new stages")
    check(not any(s["phase"] == "initialization" for s in graph if s.get("plugin") == "hw"),
          "no hw stage in Initialization")
    old = {s["slug"]: s for s in json.loads((before / harness / "tools" / "data" / "stage-graph.json").read_text())}
    for slug, node in old.items():
        new = by_slug.get(slug, {})
        check(new.get("produces") == node.get("produces"), f"{slug}: produces unchanged")

    stages_before, stages_after = before / harness / "aidlc-common" / "stages", after / harness / "aidlc-common" / "stages"
    for rel, marks in FRAGMENTS.items():
        text = (stages_after / rel).read_text()
        for first, mark, then in marks:
            start, at, end = text.find(first), text.find(mark), text.find(then)
            check(0 <= start < at < end, f"{rel}: '{mark}' is spliced in after '{first}' and before '{then}'")
        check(len(re.findall(r"<!-- plugin:hw:", text)) == len(marks), f"{rel}: {len(marks)} fragment(s) of hw")
        for m in re.finditer(r"<!-- plugin:hw:[^>]*-->", text):
            fences = len(re.findall(r"^\s*```", text[:m.start()], re.M))
            check(fences % 2 == 0, f"{rel}: {m.group(0)} is outside any code block")
    for path in sorted(stages_before.rglob("*.md")):
        rel = path.relative_to(stages_before)
        old_front, old_body = split(path.read_text())
        new_front, new_body = split((stages_after / rel).read_text())
        check(normal(BLOCK.sub("\n\n", new_body)) == normal(old_body), f"{rel}: body unchanged outside the plugin's blocks")
        added = [ln for ln in difflib.ndiff(old_front, new_front) if ln[:2] in ("+ ", "- ")]
        want = CONSUMES.get(str(rel), [])
        check(added == want, f"{rel}: frontmatter unchanged" + (" except the plugin's consumes" if want else ""))
    print(f"\nPlugin stages as compiled:")
    for slug in NEW_STAGES:
        if slug in by_slug:
            i = order.index(slug)
            print(f"  {by_slug[slug]['phase']} {by_slug[slug]['number']} {slug} (after {order[i - 1]})")
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
