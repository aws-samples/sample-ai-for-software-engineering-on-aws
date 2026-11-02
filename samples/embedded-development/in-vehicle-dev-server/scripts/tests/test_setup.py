"""setup.sh, cleanup.sh and their helpers, without touching the Kiro Crew on this machine: a temporary HOME, a temporary
install record, a stand-in kcapi.sh that answers from a JSON file and logs every call, and a stand-in docker.

    python3 -m pytest -q scripts/tests
"""
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

SAMPLE = Path(__file__).resolve().parents[2]
SCRIPTS = SAMPLE / "scripts"
EXPERTS = {"vstatd-developer": "aidlc-developer-agent", "vstatd-architect": "aidlc-architect-agent",
           "vstatd-quality": "aidlc-quality-agent", "vstatd-architecture-reviewer": "aidlc-architecture-reviewer-agent"}
MEMBERS = list(EXPERTS)

KCAPI = """#!/usr/bin/env python3
import json, os, sys
method, path = sys.argv[1], sys.argv[2]
with open(os.environ["FAKE_KC_LOG"], "a") as f:
    f.write(json.dumps([method, path] + sys.argv[3:]) + "\\n")
answers = json.load(open(os.environ["FAKE_KC"]))
print(json.dumps(answers.get(path, {"error": "not found"}) if method == "GET" else {"error": "the stand-in takes no writes"}))
"""


def run_py(*args, env=None):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, env=env, check=False)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A HOME, an install record and stand-ins for kcapi.sh, docker and the kirocrew program."""
    h = tmp_path / "home"
    h.mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "kcapi").write_text(KCAPI, encoding="utf-8")
    (bin_ / "docker").write_text("#!/bin/sh\n[ \"$1\" = version ] && echo 27.0 ; exit 0\n", encoding="utf-8")
    (bin_ / "kirocrew").write_text("#!/bin/sh\n", encoding="utf-8")
    for p in bin_.iterdir():
        p.chmod(0o755)
    env = {**os.environ, "HOME": str(h), "PATH": f"{bin_}:{os.environ['PATH']}",
           "VSTATD_KCAPI": str(bin_ / "kcapi"), "VSTATD_KIROCREW_BIN": str(bin_ / "kirocrew"),
           "VSTATD_INSTALL_STATE": str(tmp_path / "install-state.json"),
           "FAKE_KC": str(tmp_path / "kc.json"), "FAKE_KC_LOG": str(tmp_path / "kc.log")}
    return {"home": h, "env": env, "state": tmp_path / "install-state.json", "kc": tmp_path / "kc.json",
            "log": tmp_path / "kc.log", "tmp": tmp_path}


def crew(rig, apps=None, agents=(), workspaces=(), sources=()):
    rig["kc"].write_text(json.dumps({
        "/api/health": {"ok": True}, "/api/version": {"version": "0.12.0-test"},
        "/api/apps/vstatd-team": apps or {"error": "not found"},
        "/api/agents": {"agents": list(agents)}, "/api/workspaces": {"workspaces": list(workspaces)},
        "/api/knowledge/sources": {"sources": list(sources)}}), encoding="utf-8")


def calls(rig):
    return [json.loads(ln) for ln in rig["log"].read_text().splitlines()] if rig["log"].exists() else []


def test_state_records_lists_once_each(home):
    env = home["env"]
    assert run_py(SCRIPTS / "state.py", "has", "created", "app", env=env).returncode == 1
    for v in ("app", "app", "workspace"):
        assert run_py(SCRIPTS / "state.py", "add", "created", v, env=env).returncode == 0
    assert run_py(SCRIPTS / "state.py", "has", "created", "app", env=env).returncode == 0
    assert run_py(SCRIPTS / "state.py", "list", "created", env=env).stdout.split() == ["app", "workspace"]
    assert json.loads(home["state"].read_text()) == {"created": ["app", "workspace"]}
    assert run_py(SCRIPTS / "state.py", "list", "members", env=env).stdout.strip() == ""
    assert run_py(SCRIPTS / "state.py", "remove", "x", env=env).returncode == 2


def test_the_templates_are_the_four_experts_with_the_vstatd_note(tmp_path):
    out = tmp_path / "tpl"
    r = run_py(SAMPLE / "agents" / "kiro-crew" / "make_templates.py", SAMPLE / "vendor" / "aidlc-workflows" / "agents",
               out, "/opt/kirocrew")
    assert r.returncode == 0 and r.stdout.startswith("4 templates")
    assert sorted(p.stem for p in out.glob("*.json")) == sorted(MEMBERS)
    for name in MEMBERS:
        t = json.loads((out / f"{name}.json").read_text(encoding="utf-8"))
        assert t["name"] == name and " · AI-DLC " in t["description"]
        assert t["tools"] == t["allowedTools"] == ["fs_read", "fs_write", "execute_bash", "@kirocrew-core"]
        assert t["mcpServers"] == {"kirocrew-core": {"command": "/opt/kirocrew", "args": ["mcp-core"]}}
        official = (SAMPLE / "vendor" / "aidlc-workflows" / "agents" / f"{EXPERTS[name]}.md").read_text(encoding="utf-8")
        body = official.split("---", 2)[2].replace("{{HARNESS_DIR}}", "aidlc/official").strip()
        assert t["prompt"].startswith(body) and "{{HARNESS_DIR}}" not in t["prompt"]
        assert "来源「vstatd」" in t["prompt"] and "local_knowledge_search" in t["prompt"]
        assert "--trust-all-tools" not in json.dumps(t)
    assert run_py(SAMPLE / "agents" / "kiro-crew" / "make_templates.py", out).returncode == 2


def test_the_vendored_definitions_are_unmodified_copies():
    vendored = SAMPLE / "vendor" / "aidlc-workflows"
    upstream = SAMPLE.parents[1] / "agent-team-on-kiro-crew" / "vendor" / "aidlc-workflows"
    if not upstream.is_dir():
        pytest.skip("the agent-team sample is not beside this one")
    assert sorted(p.name for p in (vendored / "agents").iterdir()) == sorted(f"{e}.md" for e in EXPERTS.values())
    for rel in ["LICENSE", *(f"agents/{e}.md" for e in EXPERTS.values())]:
        assert (vendored / rel).read_bytes() == (upstream / rel).read_bytes(), rel


def test_a_template_with_the_same_name_is_backed_up_once_and_put_back(home):
    env, tmp = home["env"], home["tmp"]
    built, agents, backup = tmp / "built", home["home"] / ".kiro" / "agents", home["home"] / ".kiro" / "agents" / ".bk"
    r = run_py(SAMPLE / "agents" / "kiro-crew" / "make_templates.py", SAMPLE / "vendor" / "aidlc-workflows" / "agents",
               built, "/opt/kirocrew")
    assert r.returncode == 0
    agents.mkdir(parents=True)
    theirs = '{"name": "vstatd-developer", "prompt": "another sample\'s"}\n'
    (agents / "vstatd-developer.json").write_text(theirs, encoding="utf-8")  # e.g. one a person wrote
    same = (built / "vstatd-quality.json").read_text(encoding="utf-8")
    (agents / "vstatd-quality.json").write_text(same, encoding="utf-8")  # already there, identical: not setup's
    (agents / "other-agent.json").write_text("{}\n", encoding="utf-8")

    plan = run_py(SCRIPTS / "templates.py", "plan", built, agents, backup, env=env)
    assert plan.returncode == 0 and not backup.exists() and not home["state"].exists()  # a plan changes nothing
    assert (agents / "vstatd-developer.json").read_text() == theirs
    first = run_py(SCRIPTS / "templates.py", "install", built, agents, backup, env=env).stdout.splitlines()
    assert plan.stdout.splitlines() == first
    assert "= vstatd-quality (unchanged)" in first and "+ vstatd-architect" in first
    assert any(ln.startswith("~ vstatd-developer: exists with other content, backed up") for ln in first)
    assert (backup / "vstatd-developer.json").read_text() == theirs
    assert (agents / "vstatd-developer.json").read_text() == (built / "vstatd-developer.json").read_text()
    state = json.loads(home["state"].read_text())
    assert sorted(state["templates"]) == ["vstatd-architect", "vstatd-architecture-reviewer"]
    assert state["backed_up"] == ["vstatd-developer"]

    again = run_py(SCRIPTS / "templates.py", "install", built, agents, backup, env=env).stdout.splitlines()
    assert all(ln.endswith("(unchanged)") for ln in again) and json.loads(home["state"].read_text()) == state
    (agents / "vstatd-developer.json").write_text('{"edited": true}\n', encoding="utf-8")
    assert "~ vstatd-developer (updated)" in run_py(SCRIPTS / "templates.py", "install", built, agents, backup,
                                                         env=env).stdout  # the backup of theirs is kept, not this
    assert (backup / "vstatd-developer.json").read_text() == theirs

    gone = run_py(SCRIPTS / "templates.py", "remove", agents, backup, env=env).stdout.splitlines()
    assert sorted(gone) == ["- vstatd-architect", "- vstatd-architecture-reviewer", "< vstatd-developer (put back)"]
    assert sorted(p.name for p in agents.iterdir()) == ["other-agent.json", "vstatd-developer.json", "vstatd-quality.json"]
    assert (agents / "vstatd-developer.json").read_text() == theirs and not backup.exists()


@pytest.mark.skipif(platform.system() != "Darwin", reason="setup.sh runs on macOS")
def test_setup_dry_run_says_what_it_would_do_and_writes_nothing(home):
    crew(home, agents=[{"name": "vstatd-developer", "workspace": "taoyuan"}])
    r = subprocess.run(["bash", str(SAMPLE / "setup.sh"), "--dry-run"], capture_output=True, text=True, env=home["env"])
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "Kiro Crew 0.12.0-test" in out and "would build the board and install the app vstatd-team" in out
    assert "would record this folder in" in out and "data/sample.json" in out
    assert "would create it (folder" in out
    assert "! vstatd-developer exists in the workspace taoyuan" in out and "would add vstatd-quality" in out
    assert "+ vstatd-architect" in out and "would add it (" in out
    assert "docker build --platform linux/amd64 -t vstatd-build:amd64 reference-project/tools/" in out
    assert "bench/build-target.sh" in out and "Dry run: nothing was changed." in out
    assert {c[0] for c in calls(home)} == {"GET"}  # read only
    assert not home["state"].exists() and not (home["home"] / ".kiro").exists() and not (home["home"] / "workplace").exists()

    crew(home, apps={"name": "vstatd-team"}, workspaces=[{"name": "vstatd"}], sources=[{"name": "vstatd"}],
         agents=[{"name": m, "workspace": "vstatd"} for m in MEMBERS])
    again = subprocess.run(["bash", str(SAMPLE / "setup.sh"), "--dry-run"], capture_output=True, text=True, env=home["env"]).stdout
    assert "would update the app vstatd-team in place" in again
    assert again.count(" exists\n") == 2 + len(MEMBERS)  # the workspace, the knowledge source, the members


def test_cleanup_dry_run_lists_exactly_what_setup_recorded(home):
    crew(home)
    env, sh = home["env"], ["bash", str(SAMPLE / "cleanup.sh"), "--dry-run"]
    first = subprocess.run(sh, capture_output=True, text=True, env=env)
    assert first.returncode == 0 and "nothing: setup.sh has recorded nothing in this folder" in first.stdout
    assert "docker volume rm cc1-images" in first.stdout and "rm -rf ~/.cc1-bench" in first.stdout
    for key, value in (("created", "workspace"), ("created", "team_home"), ("members", "vstatd-quality"),
                       ("templates", "vstatd-architect"), ("backed_up", "vstatd-developer")):
        run_py(SCRIPTS / "state.py", "add", key, value, env=env)
    out = subprocess.run(sh, capture_output=True, text=True, env=env).stdout
    listed = [ln.strip() for ln in out.split("This removes what setup.sh created here:")[1].split("(dry run")[0].splitlines() if ln.strip().startswith("- ")]
    home_ = env["HOME"]
    assert listed == ["- 1 Kiro Crew members: vstatd-quality", "- the Kiro Crew workspace vstatd",
                      f"- 1 agent templates in {home_}/.kiro/agents/: vstatd-architect",
                      "- and puts back 1 agent templates it replaced: vstatd-developer",
                      f"- {home_}/workplace/vstatd (the knowledge copy)"]
    assert "the app vstatd-team" not in out and "(dry run: nothing removed)" in out
    assert calls(home) == []  # a dry run asks Kiro Crew nothing
