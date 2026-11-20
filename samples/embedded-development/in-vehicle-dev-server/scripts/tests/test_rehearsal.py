"""rehearsal/repeatability/measure.py, without a container: a stand-in for subprocess.run records the argv.

    python3 -m pytest -q scripts/tests/test_rehearsal.py
"""
import importlib.util
import json
import os
import subprocess
from pathlib import Path

SAMPLE = Path(__file__).resolve().parents[2]


def measure_module():
    spec = importlib.util.spec_from_file_location("cc1_measure", SAMPLE / "rehearsal" / "repeatability" / "measure.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_check_container_runs_as_this_user_so_that_it_leaves_no_rows_only_root_can_remove(tmp_path, monkeypatch):
    """A root container's rows under -v <out>:/m cannot be removed by the user afterwards on a Linux host, the same
    as the build container's results (app/backend/team/checks.py). HOME comes with --user: this uid has no
    /etc/passwd entry in the image, so Docker would set the unwritable HOME=/."""
    mod = measure_module()
    seen = []

    def fake_run(cmd, **kw):
        seen.append(list(cmd))
        results = tmp_path / "results" / "r1"
        (results / "logdiff.json").write_text(json.dumps({"verdict": "PASS"}))
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    verdict = mod.run_check("logdiff", tmp_path, tmp_path / "runs" / "r1", "docker", "vstatd-build:arm64",
                            tmp_path / "triage")
    assert verdict == "PASS"
    cmd = seen[0]
    assert cmd.count("--user") == 1 and cmd[cmd.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert cmd[cmd.index("--user") + 2:cmd.index("--user") + 4] == ["-e", "HOME=/tmp"]
    assert cmd.index("--user") < cmd.index("vstatd-build:arm64")
