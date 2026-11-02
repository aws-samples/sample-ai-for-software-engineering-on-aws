#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""checks/runtime-limits.sh: peak memory and threads of `vstatd` on the replay, within [CC1-PN §3].

Reads only the results the bench took after the replay ended [CC1-PN §8.5]. Pass: peak RSS (VmHWM) and the thread
count at the end within the limits, on the approved build. CPU time is reported relative to the baseline on the same
target and is never pass or fail. Results from the emulated CC-1 are labelled emulation.
"""

import sys

import common as c
import rundir


def body(args, r):
    lim = c.limits()
    try:
        run, base = rundir.load_pair(args.run, args.baseline, r, figures=True)
        rundir.load_log(f"{args.run}/run.jsonl", "run log")
    except rundir.Problem as p:
        r.reason(str(p))
        return p.verdict, "cannot judge the run" if p.verdict == c.BLOCKED else "wrong run"
    d = r.data["details"]
    d.update({"vm_hwm_kib": run["vm_hwm_kib"], "peak_rss_limit_kib": lim["peak_rss_kib"],
              "baseline_vm_hwm_kib": base["vm_hwm_kib"], "threads_at_end": run["threads_at_end"],
              "threads_limit": lim["threads_at_end"], "cpu_ms": run["cpu_ms"], "baseline_cpu_ms": base["cpu_ms"],
              "cpu_relative_to_baseline": round(run["cpu_ms"] / base["cpu_ms"], 3) if base["cpu_ms"] else None,
              "note": "CPU time is reported, not judged (CC1-PN §3)"})
    if run["vm_hwm_kib"] > lim["peak_rss_kib"]:
        r.reason(f"peak RSS {run['vm_hwm_kib']} KiB is over the limit of {lim['peak_rss_kib']} KiB (CC1-PN §3); "
                 f"baseline {base['vm_hwm_kib']} KiB")
    if run["threads_at_end"] > lim["threads_at_end"]:
        r.reason(f"{run['threads_at_end']} threads at the end of the replay, limit {lim['threads_at_end']} (CC1-PN §3)")
    summary = (f"peak RSS {run['vm_hwm_kib']} of {lim['peak_rss_kib']} KiB (baseline {base['vm_hwm_kib']}), "
               f"{run['threads_at_end']} threads, CPU x{d['cpu_relative_to_baseline']} of baseline; {r.data['tier']}")
    return (c.FAIL if r.data["reasons"] else c.PASS), summary


def add_args(p):
    p.add_argument("--run", required=True, help="run directory: run.jsonl and run-result.json")
    p.add_argument("--baseline", required=True, help="baseline directory: baseline.jsonl and baseline-result.json")


if __name__ == "__main__":
    sys.exit(c.main("runtime-limits", "emulation", add_args, body))
