#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""checks/logdiff.sh: the runtime log of the run against the baseline log of the same replay [CC1-PN §6].

Matching (§6.3): two entries match when `ev` and every compared field are equal and their `t_ms` differ by at most
the window of limits.json (20 ms). Baseline entries are taken in order; each is paired with the first unpaired run
entry that matches it. Baseline entries with the same `t_ms` (one decoding step) must keep their order in the run.
Every entry left unpaired on either side is a difference. §6.2 fields are ignored. Pass: every difference is an
allowed difference of the approved triage (§6.4). Nothing is filtered out before the comparison.
"""

import json
import sys

import common as c
import rundir


def key(entry, ignored):
    skip = set(ignored.get(entry["ev"], []))
    return (entry["ev"],) + tuple(sorted((k, v) for k, v in entry.items() if k not in ("t_ms", "ev") and k not in skip))


def compare(baseline, run, window, ignored):
    """Returns (pairs, unpaired baseline indices, unpaired run indices, order violations)."""
    by_key = {}
    for j, e in enumerate(run):
        by_key.setdefault(key(e, ignored), []).append(j)
    used = [False] * len(run)
    pairs = {}
    for i, b in enumerate(baseline):
        for j in by_key.get(key(b, ignored), []):
            if used[j]:
                continue
            if abs(run[j]["t_ms"] - b["t_ms"]) <= window:
                used[j] = True
                pairs[i] = j
                break
    order = []
    i = 0
    while i < len(baseline):
        k = i
        while k + 1 < len(baseline) and baseline[k + 1]["t_ms"] == baseline[i]["t_ms"]:
            k += 1
        paired = [(n, pairs[n]) for n in range(i, k + 1) if n in pairs]
        for (n1, j1), (n2, j2) in zip(paired, paired[1:]):
            if j2 < j1:
                order.append((n1, n2, j1, j2))
        i = k + 1
    return pairs, [i for i in range(len(baseline)) if i not in pairs], [j for j in range(len(run)) if not used[j]], order


def allowed_match(spec, entry, window, ignored):
    """An allowed difference names the whole entry (ev and every compared field); t_ms, if given, within the window."""
    want = spec["entry"]
    if key(dict(want, t_ms=0), ignored) != key(entry, ignored):
        return False
    return "t_ms" not in want or abs(want["t_ms"] - entry["t_ms"]) <= window


def fmt(e):
    return json.dumps(e, separators=(",", ":"))


def body(args, r):
    lim = c.limits()
    window, ignored = lim["log_time_window_ms"], lim["log_ignored_fields"]
    triage, problems = c.load_triage(args.triage)
    r.input("triage", args.triage)
    if problems:
        for p in problems:
            r.reason(f"triage: {p}")
        return c.BLOCKED, "no valid approved triage"
    try:
        rundir.load_pair(args.run, args.baseline, r)
        baseline = rundir.load_log(f"{args.baseline}/baseline.jsonl", "baseline log")
        run = rundir.load_log(f"{args.run}/run.jsonl", "run log")
    except rundir.Problem as p:
        r.reason(str(p))
        return p.verdict, "cannot judge the run" if p.verdict == c.BLOCKED else "wrong run"

    pairs, only_base, only_run, order = compare(baseline, run, window, ignored)
    diffs = [("baseline", baseline[i]) for i in only_base] + [("run", run[j]) for j in only_run]
    budget = [dict(spec, left=spec.get("count", 1)) for spec in triage.get("allowed_log_differences", [])]
    allowed, unexplained = [], []
    for side, e in diffs:
        spec = next((s for s in budget if s["left"] > 0 and s["side"] == side and allowed_match(s, e, window, ignored)), None)
        if spec:
            spec["left"] -= 1
            allowed.append({"side": side, "entry": e, "finding": spec["finding"]})
        else:
            unexplained.append((side, e))
    diff_lines = []
    for side, e in sorted(unexplained, key=lambda d: d[1]["t_ms"]):
        diff_lines.append(f"{'-' if side == 'baseline' else '+'} {fmt(e)}")
        r.reason(f"{'only in the baseline' if side == 'baseline' else 'only in the run'}: {fmt(e)}")
    for n1, n2, j1, j2 in order:
        diff_lines.append(f"! order: baseline {fmt(baseline[n1])} before {fmt(baseline[n2])}, reversed in the run")
        r.reason(f"order within one decoding step changed (t_ms {baseline[n1]['t_ms']}): "
                 f"{baseline[n1]['ev']} and {baseline[n2]['ev']}")
    (r.dir / "logdiff.diff").write_text("\n".join(diff_lines) + ("\n" if diff_lines else ""))
    r.data["details"].update({
        "baseline_entries": len(baseline), "run_entries": len(run), "paired": len(pairs),
        "differences": len(diffs), "allowed": allowed, "unexplained": len(unexplained), "order_changes": len(order),
        "allowed_not_seen": [{k: s[k] for k in ("finding", "side", "entry")} | {"missing": s["left"]}
                             for s in budget if s["left"] > 0],
        "window_ms": window, "diff": str(r.dir / "logdiff.diff")})
    summary = (f"{len(pairs)} of {len(baseline)} baseline entries paired; {len(unexplained)} unexplained "
               f"difference(s), {len(allowed)} allowed, {len(order)} order change(s); {r.data['tier']}")
    return (c.FAIL if unexplained or order else c.PASS), summary


def add_args(p):
    p.add_argument("--run", required=True, help="run directory: run.jsonl and run-result.json")
    p.add_argument("--baseline", required=True, help="baseline directory: baseline.jsonl and baseline-result.json")
    p.add_argument("--triage", required=True, help="the approved triage (JSON, checks/README.md)")


if __name__ == "__main__":
    sys.exit(c.main("logdiff", "emulation", add_args, body))
