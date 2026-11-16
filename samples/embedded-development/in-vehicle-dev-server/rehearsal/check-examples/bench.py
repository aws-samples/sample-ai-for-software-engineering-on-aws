#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""The after-deploy checks on the bench: the F-008 wrong fix fails logdiff, the F-021 wrong fix fails runtime-limits.

For facilitators, run on the bench host as the bench owner, after run.py (README.md). Every deploy and replay goes
through bench/cc1.sh, so each one waits for an approval at the operator console (bench/console.py) of the state
directory given; nothing here approves anything.

    bench.py --state <bench state dir> --artifacts <run.py's OUT>/artifacts --out <data dir> [--runs 5] \\
             [--image vstatd-build:arm64]

One fresh boot of the emulated CC-1 (stop, start --shift 3, wait). The release build is deployed and replayed once as
the baseline, then each build is deployed and replayed --runs times: the release, the F-008 wrong fix and the F-021
wrong fix. checks/logdiff.sh and checks/runtime-limits.sh judge every run against that baseline in the build
container, with the approved triage of run.py, which allows no log difference. One row per run goes to
<out>/runs.csv; the table of verdicts against the expected ones is printed at the end. Exits non-zero when any check
gave another verdict than expected.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
SAMPLE = HERE.parents[1]
# run_check(), sh() and dt_stats() of the repeatability measurement: the same check calls, so the two agree.
_spec = importlib.util.spec_from_file_location("measure", HERE.parent / "repeatability" / "measure.py")
measure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measure)

# build → (logdiff, runtime-limits) expected on every run.
EXPECTED = {"release": ("PASS", "PASS"), "f008": ("FAIL", "PASS"), "f021": ("PASS", "FAIL")}
LABEL = {"release": "release (F-031 only)", "f008": "F-008 wrong fix", "f021": "F-021 wrong fix"}
FIELDS = ["build", "run", "digest", "logdiff", "runtime_limits", "logdiff_reason", "runtime_limits_reason",
          "vm_hwm_kib", "threads_at_end", "cpu_ms", "max_abs_dt_ms", "n_gt_20ms", "unpaired_at_200ms",
          "replay_wall_s", "load1_at_start"]


def reason(out, run, name):
    res = json.loads((out / "results" / run.name / f"{name}.json").read_text())
    return (res.get("reasons") or [""])[0][:110]


def bench_runs(a, art, out, triage, digests, env, cc1, rows):
    sh = measure.sh
    sh([*cc1, "start", "--shift", "3"], env)
    sh([*cc1, "wait", "900"], env)
    with open(out / "runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for build in EXPECTED:
            sh([*cc1, "deploy", art / build], env)
            if build == "release":
                sh([*cc1, "replay", "--kind", "baseline", "--out", out / "baseline"], env)
            for n in range(1, a.runs + 1):
                run = out / "runs" / f"{build}-r{n:02d}"
                load1, start = os.getloadavg()[0], time.time()
                sh([*cc1, "replay", "--kind", "run", "--out", run], env)
                res = json.loads((run / "run-result.json").read_text())
                row = {"build": build, "run": n, "digest": digests[build][:12],
                       "replay_wall_s": round(time.time() - start, 1), "load1_at_start": round(load1, 2),
                       "vm_hwm_kib": res.get("vm_hwm_kib"), "threads_at_end": res.get("threads_at_end"),
                       "cpu_ms": res.get("cpu_ms"),
                       "logdiff": measure.run_check("logdiff", out, run, a.docker, a.image, triage),
                       "runtime_limits": measure.run_check("runtime-limits", out, run, a.docker, a.image, triage)}
                row["logdiff_reason"] = reason(out, run, "logdiff")
                row["runtime_limits_reason"] = reason(out, run, "runtime-limits")
                stats = measure.dt_stats(out, run)
                row.update({k: stats[k] for k in ("max_abs_dt_ms", "n_gt_20ms", "unpaired_at_200ms")})
                w.writerow(row)
                f.flush()
                rows.append(row)
                measure.log(f"{build} run {n}: logdiff {row['logdiff']}, runtime-limits {row['runtime_limits']}, "
                            f"VmHWM {row['vm_hwm_kib']} KiB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--artifacts", required=True, help="run.py's OUT/artifacts: release, f008, f021, triage.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", type=int, default=5)
    arch = "arm64" if platform.machine() in ("arm64", "aarch64") else "amd64"
    ap.add_argument("--image", default=f"vstatd-build:{arch}")
    ap.add_argument("--docker", default=shutil.which("docker") or "docker")
    a = ap.parse_args()
    if subprocess.run([a.docker, "image", "inspect", a.image], capture_output=True).returncode != 0:
        raise SystemExit(f"no image {a.image}; build it from reference-project/tools/Dockerfile or give --image")
    art, out = pathlib.Path(a.artifacts).resolve(), pathlib.Path(a.out).resolve()
    if out.exists():
        raise SystemExit(f"{out} exists; give a new data directory")
    (out / "runs").mkdir(parents=True)
    triage = out / "triage.json"
    shutil.copyfile(art / "triage.json", triage)
    shutil.copyfile(art / "triage.json.sha256", str(triage) + ".sha256")
    digests = {b: hashlib.sha256((art / b).read_bytes()).hexdigest() for b in EXPECTED}
    (out / "builds.json").write_text(json.dumps(digests, indent=2) + "\n")
    env = {**os.environ, "CC1_BENCH_STATE": a.state, "CC1_REQUESTER": "check examples on the bench"}
    cc1 = ["bash", SAMPLE / "bench" / "cc1.sh"]
    t0, rows = time.time(), []
    sh = measure.sh
    sh([*cc1, "stop"], env, check=False)
    try:
        bench_runs(a, art, out, triage, digests, env, cc1, rows)
    finally:  # also after a refused or timed-out request, which stops measure.sh
        sh([*cc1, "stop"], env, check=False)

    failed = 0
    print("\n| Build | Runs | `logdiff` expected | `logdiff` | `runtime-limits` expected | `runtime-limits` "
          "| VmHWM KiB |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for build, (want_ld, want_rl) in EXPECTED.items():
        rs = [r for r in rows if r["build"] == build]
        ld = sorted({r["logdiff"] for r in rs})
        rl = sorted({r["runtime_limits"] for r in rs})
        bad = sum(r["logdiff"] != want_ld or r["runtime_limits"] != want_rl for r in rs)
        failed += bad
        hwm = [r["vm_hwm_kib"] for r in rs if isinstance(r["vm_hwm_kib"], int)]
        span = f"{min(hwm):,} to {max(hwm):,}" if hwm else ""
        print(f"| {LABEL[build]} | {len(rs)} | {want_ld} | {'/'.join(ld)} | {want_rl} | {'/'.join(rl)} | {span} |")
    print(f"\n{len(rows) - failed} of {len(rows)} runs as expected, in {round((time.time() - t0) / 60, 1)} min; "
          f"data in {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
