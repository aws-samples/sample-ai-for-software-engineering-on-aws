# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Run and baseline directories: what the bench hands to the after-deploy checks [CC1-PN §5, §8.4, §8.5].

A run directory holds run.jsonl (the runtime log of the run, up to SERVICE_STOP) and run-result.json; a baseline
directory holds baseline.jsonl and baseline-result.json with the same fields. checks/README.md describes them.
"""

import json
import pathlib
import re

import common as c

FIELDS = {"replay_id": str, "target": str, "replay_finished": bool, "replay_end": str,
          "figures_after_replay_end": bool, "approved_digest": str, "readback_digest": str}
FIGURES = {"vm_hwm_kib": int, "threads_at_end": int, "cpu_ms": int}
TARGETS = {"emulated-cc1": "emulation", "real-cc1": "real target"}
# How the bench knew the replay had ended (CC1-PN §8.5). The exit status of the script that started it does not count.
REPLAY_ENDS = {"player-end-of-drive"}
ICOUNT = re.compile(r"-icount\s+(shift=\d+,sleep=off)\b")


class Problem(Exception):
    """A run or baseline that cannot be judged (BLOCKED), or a run that is wrong (FAIL)."""

    def __init__(self, verdict, text):
        super().__init__(text)
        self.verdict = verdict


def load_result(path, what, figures=False):
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError) as e:
        raise Problem(c.BLOCKED, f"{what}: {e}")
    for k, t in (FIELDS | FIGURES if figures else FIELDS).items():
        if not isinstance(data.get(k), t) or (t is int and isinstance(data.get(k), bool)):
            raise Problem(c.BLOCKED, f"{what}: field {k} missing or not {t.__name__}")
    if data["target"] not in TARGETS:
        raise Problem(c.BLOCKED, f"{what}: target must be one of {', '.join(TARGETS)}")
    if data["target"] == "emulated-cc1":
        m = ICOUNT.search(data.get("qemu_command") or "")
        if not m:
            raise Problem(c.BLOCKED, f"{what}: the QEMU command line with -icount shift=<n>,sleep=off is not recorded "
                                     "(CC1-PN §2.2)")
        data["icount"] = m.group(1)
    if data["replay_end"] not in REPLAY_ENDS:
        raise Problem(c.BLOCKED, f"{what}: replay_end {data['replay_end']!r} is not a recognised end of the replay "
                                 f"({', '.join(sorted(REPLAY_ENDS))}; CC1-PN §8.5)")
    if not data["replay_finished"] or not data["figures_after_replay_end"]:
        raise Problem(c.BLOCKED, f"{what}: the run had not ended when its results were taken (CC1-PN §8.5); "
                                 f"replay_end: {data['replay_end']!r}")
    return data


def load_log(path, what):
    """Entries of a runtime log [CC1-PN §5]. A line that is not in the format is a FAIL; a log that does not end
    with SERVICE_STOP is incomplete (BLOCKED)."""
    try:
        lines = pathlib.Path(path).read_text().splitlines()
    except OSError as e:
        raise Problem(c.BLOCKED, f"{what}: {e}")
    if not [ln for ln in lines if ln.strip()]:
        raise Problem(c.BLOCKED, f"{what}: the log is empty")
    entries, fields = [], c.log_fields()
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            pairs = json.loads(line, object_pairs_hook=lambda kv: kv)
        except ValueError:
            raise Problem(c.FAIL, f"{what} line {n}: not JSON: {line[:120]}")
        is_object = isinstance(pairs, list) and pairs and all(isinstance(x, tuple) for x in pairs)
        keys = [k for k, _ in pairs] if is_object else []
        e = dict(pairs) if keys else None
        if not e or len(keys) != len(e) or keys[:2] != ["t_ms", "ev"] or not isinstance(e["t_ms"], int) \
                or isinstance(e["t_ms"], bool) or not all(isinstance(e[k], str) for k in keys[1:]):
            raise Problem(c.FAIL, f"{what} line {n}: not in the format of CC1-PN §5.2-§5.3: {line[:120]}")
        if e["ev"] not in fields or keys[2:] != fields[e["ev"]]:
            raise Problem(c.FAIL, f"{what} line {n}: event or fields not as in VSTATD-IF §7.1 "
                                  f"(expected {fields.get(e['ev'], 'a known event')}): {line[:120]}")
        entries.append(e)
    if entries[-1]["ev"] != "SERVICE_STOP":
        raise Problem(c.BLOCKED, f"{what}: does not end with SERVICE_STOP; the log was not collected to the end "
                                 "(CC1-PN §8.5)")
    return entries


def load_pair(run_dir, baseline_dir, r, figures=False):
    """Run and baseline results, checked to be comparable. Raises Problem."""
    run_dir, baseline_dir = pathlib.Path(run_dir), pathlib.Path(baseline_dir)
    for name, p in (("run_result", run_dir / "run-result.json"), ("run_log", run_dir / "run.jsonl"),
                    ("baseline_result", baseline_dir / "baseline-result.json"),
                    ("baseline_log", baseline_dir / "baseline.jsonl")):
        r.input(name, p)
    run = load_result(run_dir / "run-result.json", "run", figures)
    base = load_result(baseline_dir / "baseline-result.json", "baseline", figures)
    r.data["tier"] = TARGETS[run["target"]]
    r.data["details"].update({"replay_id": run["replay_id"], "target": run["target"],
                              "deployed_digest": run["readback_digest"], "approved_digest": run["approved_digest"]})
    if run["readback_digest"] != run["approved_digest"]:
        raise Problem(c.FAIL, f"installed vstatd {run['readback_digest'][:12]} is not the approved build "
                              f"{run['approved_digest'][:12]} (CC1-PN §8.4)")
    if run["replay_id"] != base["replay_id"] or run["target"] != base["target"]:
        raise Problem(c.BLOCKED, f"run ({run['replay_id']}, {run['target']}) and baseline ({base['replay_id']}, "
                                 f"{base['target']}) are not the same replay on the same target")
    if run.get("icount") != base.get("icount"):
        raise Problem(c.BLOCKED, f"run and baseline use different instruction-counter settings "
                                 f"({run.get('icount')} and {base.get('icount')}); timing is not comparable")
    return run, base
