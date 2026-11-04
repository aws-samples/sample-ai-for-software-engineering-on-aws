#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Repeatability and memory of the emulated CC-1: boots, one baseline, many runs, the after-bench checks on each.

For facilitators, run as the bench owner. Every deploy and replay goes through bench/cc1.sh, so each one waits for an
approval at the operator console (bench/console.py) of the state directory given; nothing here approves anything.

    measure.py --state <bench state dir> --out <data dir> --normal <vstatd> --f021 <vstatd> \\
               --plan 1:baseline+20 --plan 2:20 --plan 3:20 --plan 4:f021:10

A plan entry is `<boot>:[f021:][baseline+]<runs>`: a fresh boot (stop, start --shift 3, wait), a deploy of the
normal build (or of the F-021 wrong fix), the baseline replay when named, then that many runs. Every run is compared
with the one baseline by checks/logdiff.sh and checks/runtime-limits.sh, in the build container, and one row goes to
<out>/runs.csv. The time differences per paired entry are measured with checks/lib/check_logdiff.compare() and a wide
window, so that differences beyond the checks' 20 ms show up too; the checks' own verdicts use their own window.
A file /tmp/cc1-repeatability.editing present at the start of a replay marks the row as made while the host was
also used for other work.
"""
import argparse
import csv
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
SAMPLE = HERE.parents[1]
sys.path.insert(0, str(SAMPLE / "checks" / "lib"))
import check_logdiff  # noqa: E402  (compare() only; the check itself runs in its container)
import rundir  # noqa: E402

WIDE_MS = 200
EDITING = pathlib.Path("/tmp/cc1-repeatability.editing")
FIELDS = ["boot", "replay_in_boot", "build", "logdiff", "max_abs_dt_ms", "p99_abs_dt_ms", "n_gt_10ms", "n_gt_15ms",
          "n_gt_20ms", "max_dt_ev", "max_dt_entry", "unpaired_at_200ms", "vm_hwm_kib", "threads_at_end", "cpu_ms",
          "runtime_limits", "replay_wall_s", "load1_at_start", "host_in_use"]


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def sh(args, env, check=True):
    log("$ " + " ".join(map(str, args)))
    r = subprocess.run(list(map(str, args)), env=env, text=True, capture_output=True)
    for line in (r.stdout + r.stderr).strip().splitlines()[-6:]:
        log("  " + line)
    if check and r.returncode != 0:
        raise SystemExit(f"stopped: {args[1] if len(args) > 1 else args[0]} exited with {r.returncode}")
    return r


def run_check(name, out, run, docker, image, triage):
    results = out / "results" / run.name
    results.mkdir(parents=True, exist_ok=True)
    rel = lambda p: f"/m/{p.relative_to(out)}"  # noqa: E731 - the data dir is mounted at /m
    cmd = [docker, "run", "--rm", "--network", "none", "-v", f"{SAMPLE}:/sample:ro", "-v", f"{out}:/m", image,
           f"/sample/checks/{name}.sh", "--results", rel(results), "--run", rel(run), "--baseline", rel(out / "baseline")]
    if name == "logdiff":
        cmd += ["--triage", rel(triage)]
    subprocess.run(cmd, capture_output=True)
    res = json.loads((results / f"{name}.json").read_text())
    return res["verdict"]


def dt_stats(out, run):
    lim = json.loads((SAMPLE / "checks" / "limits.json").read_text())
    ignored = lim["log_ignored_fields"]["value"]
    base = rundir.load_log(str(out / "baseline" / "baseline.jsonl"), "baseline log")
    got = rundir.load_log(str(run / "run.jsonl"), "run log")
    pairs, only_base, only_run, _ = check_logdiff.compare(base, got, WIDE_MS, ignored)
    dts = sorted(((abs(got[j]["t_ms"] - base[i]["t_ms"]), i) for i, j in pairs.items()), reverse=True)
    worst = base[dts[0][1]] if dts else {}
    values = [d for d, _ in dts]
    p99 = sorted(values)[max(0, int(round(0.99 * len(values))) - 1)] if values else ""
    detail = {k: v for k, v in worst.items() if k not in ("t_ms", "ev")}
    return {"max_abs_dt_ms": values[0] if values else "", "p99_abs_dt_ms": p99,
            "n_gt_10ms": sum(v > 10 for v in values), "n_gt_15ms": sum(v > 15 for v in values),
            "n_gt_20ms": sum(v > 20 for v in values), "max_dt_ev": worst.get("ev", ""),
            "max_dt_entry": json.dumps(dict(detail, t_ms=worst.get("t_ms")), separators=(",", ":")) if worst else "",
            "unpaired_at_200ms": len(only_base) + len(only_run)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--normal", required=True)
    ap.add_argument("--f021", required=True)
    ap.add_argument("--triage", required=True, help="an approved triage with no allowed differences, and its .sha256")
    ap.add_argument("--plan", action="append", required=True)
    ap.add_argument("--image", default="vstatd-build:arm64")
    ap.add_argument("--docker", default=shutil.which("docker") or "docker")
    a = ap.parse_args()
    out = pathlib.Path(a.out).resolve()
    (out / "runs").mkdir(parents=True, exist_ok=True)
    triage = out / "triage.json"
    shutil.copyfile(a.triage, triage)
    shutil.copyfile(a.triage + ".sha256", str(triage) + ".sha256")
    env = {**os.environ, "CC1_BENCH_STATE": a.state, "CC1_REQUESTER": "repeatability measurement"}
    cc1 = ["bash", SAMPLE / "bench" / "cc1.sh"]
    csv_path = out / "runs.csv"
    new = not csv_path.exists()
    t0 = time.time()
    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for entry in a.plan:
            boot, *rest = entry.split(":")
            build = "f021" if rest[0] == "f021" else "normal"
            spec = rest[-1]
            baseline = spec.startswith("baseline+")
            runs = int(spec.split("+")[-1])
            sh([*cc1, "stop"], env, check=False)
            sh([*cc1, "start", "--shift", "3"], env)
            sh([*cc1, "wait", "900"], env)
            sh([*cc1, "deploy", a.f021 if build == "f021" else a.normal], env)
            if baseline:
                sh([*cc1, "replay", "--kind", "baseline", "--out", out / "baseline"], env)
            for n in range(1, runs + 1):
                run = out / "runs" / f"b{boot}-r{n:02d}"
                load1, editing, start = os.getloadavg()[0], EDITING.exists(), time.time()
                sh([*cc1, "replay", "--kind", "run", "--out", run], env)
                wall = round(time.time() - start, 1)
                res = json.loads((run / "run-result.json").read_text())
                row = {"boot": boot, "replay_in_boot": n, "build": build, "replay_wall_s": wall,
                       "load1_at_start": round(load1, 2), "host_in_use": "yes" if editing else "no",
                       "vm_hwm_kib": res.get("vm_hwm_kib"), "threads_at_end": res.get("threads_at_end"),
                       "cpu_ms": res.get("cpu_ms"),
                       "logdiff": run_check("logdiff", out, run, a.docker, a.image, triage),
                       "runtime_limits": run_check("runtime-limits", out, run, a.docker, a.image, triage),
                       **dt_stats(out, run)}
                w.writerow(row)
                f.flush()
                log(f"boot {boot} run {n}: logdiff {row['logdiff']}, max |dt| {row['max_abs_dt_ms']} ms, "
                    f"VmHWM {row['vm_hwm_kib']} KiB, runtime-limits {row['runtime_limits']}")
    sh([*cc1, "stop"], env, check=False)
    log(f"done in {round((time.time() - t0) / 60, 1)} min")


if __name__ == "__main__":
    main()
