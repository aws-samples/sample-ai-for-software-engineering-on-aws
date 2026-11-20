"""setup.sh, cleanup.sh and their helpers, without touching the Kiro Crew on this machine: a temporary HOME, a temporary
install record, a stand-in kcapi.sh that answers from a JSON file and logs every call, and a stand-in docker.

    python3 -m pytest -q scripts/tests
"""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SAMPLE = Path(__file__).resolve().parents[2]
SCRIPTS = SAMPLE / "scripts"
EXPERTS = {"embedded-developer": "aidlc-developer-agent", "embedded-architect": "aidlc-architect-agent",
           "embedded-quality": "aidlc-quality-agent", "embedded-architecture-reviewer": "aidlc-architecture-reviewer-agent"}
MEMBERS = list(EXPERTS)

KCAPI = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
status = args[:1] == ["--status"]  # kcapi.sh --status: the HTTP status only
args = args[1:] if status else args
method, path = args[0], args[1]
with open(os.environ["FAKE_KC_LOG"], "a") as f:
    f.write(json.dumps(args) + "\\n")
answers = json.load(open(os.environ["FAKE_KC"]))
if "up" in answers and path not in answers["up"]:  # the owner API refuses this shell: no token
    print("kcapi: could not mint a token", file=sys.stderr)
    sys.exit(1)
gets = sum(json.loads(ln) == ["GET", path] for ln in open(os.environ["FAKE_KC_LOG"]))  # this one included
# Kiro Crew answers with an error: every time (fail), or the Nth GET of that path (fail_get)
if path in answers.get("fail", []) or gets in answers.get("fail_get", {}).get(path, []):
    print("500" if status else json.dumps({"error": "the stand-in fails this"}))
elif status:
    print("404" if answers.get(path, {"error": "not found"}) == {"error": "not found"} else "200")
elif method == "GET":
    print(json.dumps(answers.get(path, {"error": "not found"})))
elif method == "DELETE" and path not in answers.get("refuse", []):  # gone from the list that holds it
    if path in answers:
        answers[path] = {"error": "not found"}
    base, key = path.rsplit("/", 1)
    for k, v in (answers.get(base) or {}).items():
        answers[base][k] = [r for r in v if r != key
                            and not (isinstance(r, dict) and key in (r.get("name"), r.get("id")))]
    json.dump(answers, open(os.environ["FAKE_KC"], "w"))
    print(json.dumps({"ok": True}))
else:
    a = answers.get(f"{method} {path}", {"error": "the stand-in refuses this"})
    print(a if isinstance(a, str) else json.dumps(a))  # a string: a body that is not JSON
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


def crew(rig, apps=None, agents=(), workspaces=(), sources=(), trusted=(), **more):
    rig["kc"].write_text(json.dumps({
        "/api/health": {"ok": True}, "/api/version": {"version": "0.12.0-test"},
        "/api/apps/vstatd-team": apps or {"error": "not found"},
        "/api/apps/vstatd-team/runs": {"runs": []},  # the app's runs (the board's list): none
        "/api/agents": {"agents": list(agents)}, "/api/workspaces": {"workspaces": list(workspaces)},
        "/api/knowledge/sources": {"sources": list(sources)},
        "/api/security/trusted-apps": {"apps": list(trusted)}, **more}), encoding="utf-8")


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
    assert run_py(SCRIPTS / "state.py", "empty", env=env).returncode == 1
    assert run_py(SCRIPTS / "state.py", "remove", "created", "app", env=env).returncode == 0
    assert json.loads(home["state"].read_text()) == {"created": ["workspace"]}
    assert run_py(SCRIPTS / "state.py", "remove", "created", env=env).returncode == 0
    assert json.loads(home["state"].read_text()) == {}
    assert run_py(SCRIPTS / "state.py", "empty", env=env).returncode == 0
    assert run_py(SCRIPTS / "state.py", "drop", "x", env=env).returncode == 2


def test_the_templates_are_the_four_experts_with_the_vstatd_note(tmp_path):
    out = tmp_path / "tpl"
    r = run_py(SAMPLE / "agents" / "kiro-crew" / "make_templates.py", SAMPLE / "vendor" / "aidlc-workflows" / "agents",
               out, "/opt/kirocrew")
    assert r.returncode == 0 and r.stdout.startswith("4 templates")
    assert sorted(p.stem for p in out.glob("*.json")) == sorted(f"{m}-agent" for m in MEMBERS)  # not a member's name
    for name in MEMBERS:
        t = json.loads((out / f"{name}-agent.json").read_text(encoding="utf-8"))
        assert t["name"] == f"{name}-agent" and t["description"].startswith("Embedded ") and " · AI-DLC " in t["description"]
        assert t["tools"] == t["allowedTools"] == ["fs_read", "fs_write", "execute_bash", "@kirocrew-core"]
        assert t["mcpServers"] == {"kirocrew-core": {"command": "/opt/kirocrew", "args": ["mcp-core"]}}
        official = (SAMPLE / "vendor" / "aidlc-workflows" / "agents" / f"{EXPERTS[name]}.md").read_text(encoding="utf-8")
        body = official.split("---", 2)[2].replace("{{HARNESS_DIR}}", "aidlc/official").strip()
        assert t["prompt"].startswith(body) and "{{HARNESS_DIR}}" not in t["prompt"]
        assert "来源「vstatd」" in t["prompt"] and "local_knowledge_search" in t["prompt"]
        assert "--trust-all-tools" not in json.dumps(t)
        # the bypass hook, in the array form both engines load, and V3's permissions next to V2's allowedTools
        assert [h["matcher"] for h in t["hooks"]] == ["shell", "write"]
        assert all(h["trigger"] == "PreToolUse" and h["action"]["type"] == "command"
                   and h["action"]["command"].startswith("python3 -I ") and h["action"]["command"].endswith("|| exit 2")
                   and h["action"]["command"].split()[2].endswith("agents/hooks/guard.py") for h in t["hooks"])
        assert {(r["capability"], r["effect"]) for r in t["permissions"]["rules"]} == {
            ("fs_read", "allow"), ("fs_write", "allow"), ("shell", "allow"), ("skill", "allow"), ("mcp", "allow")}
        assert [r.get("match") for r in t["permissions"]["rules"] if r["capability"] == "mcp"] == [["kirocrew-core/*"]]
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
    theirs = '{"name": "embedded-developer-agent", "prompt": "another sample\'s"}\n'
    (agents / "embedded-developer-agent.json").write_text(theirs, encoding="utf-8")  # e.g. one a person wrote
    same = (built / "embedded-quality-agent.json").read_text(encoding="utf-8")
    (agents / "embedded-quality-agent.json").write_text(same, encoding="utf-8")  # already there, identical: not setup's
    (agents / "other-agent.json").write_text("{}\n", encoding="utf-8")

    plan = run_py(SCRIPTS / "templates.py", "plan", built, agents, backup, env=env)
    assert plan.returncode == 0 and not backup.exists() and not home["state"].exists()  # a plan changes nothing
    assert (agents / "embedded-developer-agent.json").read_text() == theirs
    first = run_py(SCRIPTS / "templates.py", "install", built, agents, backup, env=env).stdout.splitlines()
    assert plan.stdout.splitlines() == first
    assert "= embedded-quality-agent (unchanged)" in first and "+ embedded-architect-agent" in first
    assert any(ln.startswith("~ embedded-developer-agent: exists with other content, backed up") for ln in first)
    assert (backup / "embedded-developer-agent.json").read_text() == theirs
    assert (agents / "embedded-developer-agent.json").read_text() == (built / "embedded-developer-agent.json").read_text()
    state = json.loads(home["state"].read_text())
    assert sorted(state["templates"]) == ["embedded-architect-agent", "embedded-architecture-reviewer-agent"]
    assert state["backed_up"] == ["embedded-developer-agent"]

    again = run_py(SCRIPTS / "templates.py", "install", built, agents, backup, env=env).stdout.splitlines()
    assert all(ln.endswith("(unchanged)") for ln in again) and json.loads(home["state"].read_text()) == state
    (agents / "embedded-developer-agent.json").write_text('{"edited": true}\n', encoding="utf-8")
    assert "~ embedded-developer-agent (updated)" in run_py(SCRIPTS / "templates.py", "install", built, agents, backup,
                                                         env=env).stdout  # the backup of theirs is kept, not this
    assert (backup / "embedded-developer-agent.json").read_text() == theirs

    gone = run_py(SCRIPTS / "templates.py", "remove", agents, backup, env=env).stdout.splitlines()
    assert sorted(gone) == ["- embedded-architect-agent", "- embedded-architecture-reviewer-agent", "< embedded-developer-agent (put back)"]
    assert sorted(p.name for p in agents.iterdir()) == ["embedded-developer-agent.json", "embedded-quality-agent.json", "other-agent.json"]
    assert (agents / "embedded-developer-agent.json").read_text() == theirs and not backup.exists()


def test_a_template_an_earlier_setup_wrote_under_an_old_name_goes(home):
    env, tmp = home["env"], home["tmp"]
    built, agents, backup = tmp / "built", home["home"] / ".kiro" / "agents", home["home"] / ".kiro" / "agents" / ".bk"
    assert run_py(SAMPLE / "agents" / "kiro-crew" / "make_templates.py", SAMPLE / "vendor" / "aidlc-workflows" / "agents",
                  built, "/opt/kirocrew").returncode == 0
    agents.mkdir(parents=True)
    for old in ("embedded-developer", "vstatd-quality"):  # names earlier versions of setup used, recorded as its own
        (agents / f"{old}.json").write_text("{}\n", encoding="utf-8")
        run_py(SCRIPTS / "state.py", "add", "templates", old, env=env)
    (agents / "embedded-quality.json").write_text("{}\n", encoding="utf-8")  # not recorded: not setup's, stays
    plan = run_py(SCRIPTS / "templates.py", "plan", built, agents, backup, env=env).stdout.splitlines()
    assert "- embedded-developer (no longer used by the team)" in plan and (agents / "embedded-developer.json").exists()
    out = run_py(SCRIPTS / "templates.py", "install", built, agents, backup, env=env).stdout.splitlines()
    assert out == plan and "- vstatd-quality (no longer used by the team)" in out
    assert not (agents / "embedded-developer.json").exists() and not (agents / "vstatd-quality.json").exists()
    assert (agents / "embedded-quality.json").exists() and (agents / "embedded-developer-agent.json").exists()


@pytest.mark.skipif(platform.system() != "Darwin", reason="setup.sh runs on macOS")
def test_setup_dry_run_says_what_it_would_do_and_writes_nothing(home):
    crew(home)
    r = subprocess.run(["bash", str(SAMPLE / "setup.sh"), "--dry-run"], capture_output=True, text=True, env=home["env"])
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "Kiro Crew 0.12.0-test" in out and "would build the board and install the app vstatd-team" in out
    assert "would record this folder in" in out and "data/sample.json" in out
    assert "+ embedded-architect-agent" in out and "would add it (" in out
    assert "workspace" not in out.split("[3/5]")[1].split("[4/5]")[0] and "members" not in out  # no members (D6)
    arch = "arm64" if platform.machine() in ("arm64", "aarch64") else "amd64"  # the native image (ThreadSanitizer)
    assert f"docker build --platform linux/{arch} -t vstatd-build:{arch} reference-project/tools/" in out
    assert (f'docker run --rm --platform linux/{arch} -v vstatd-standin-sysroot:/opt/cc1-sysroot -v "$PWD":/sample:ro '
            f"vstatd-build:{arch} \\\n      python3 /sample/reference-project/tools/make-standin-sysroot.py /opt/cc1-sysroot") in out
    assert "bench/build-target.sh" in out and "Dry run: nothing was changed." in out
    assert {c[0] for c in calls(home)} == {"GET"}  # read only
    assert not home["state"].exists() and not (home["home"] / ".kiro").exists() and not (home["home"] / "workplace").exists()

    crew(home, apps={"name": "vstatd-team"}, sources=[{"name": "vstatd"}])
    again = subprocess.run(["bash", str(SAMPLE / "setup.sh"), "--dry-run"], capture_output=True, text=True, env=home["env"]).stdout
    assert "would update the app vstatd-team in place" in again
    assert again.count(" exists\n") == 1  # the knowledge source


def test_cleanup_dry_run_lists_exactly_what_setup_recorded(home):
    crew(home)
    env, sh = home["env"], ["bash", str(SAMPLE / "cleanup.sh"), "--dry-run"]
    first = subprocess.run(sh, capture_output=True, text=True, env=env)
    assert first.returncode == 0 and "nothing: setup.sh has recorded nothing in this folder" in first.stdout
    assert "docker volume rm cc1-images" in first.stdout and "rm -rf ~/.cc1-bench" in first.stdout
    assert (f"rm -rf {env['HOME']}/workplace/vstatd-team/server   # servers mode (app/README): its venv, configs, work"
            " tree and the servers' state") in first.stdout  # setup.sh does not make it, so cleanup.sh leaves it
    for key, value in (("created", "workspace"), ("created", "team_home"), ("members", "embedded-quality"),
                       ("templates", "embedded-architect"), ("backed_up", "embedded-developer")):
        run_py(SCRIPTS / "state.py", "add", key, value, env=env)
    out = subprocess.run(sh, capture_output=True, text=True, env=env).stdout
    listed = [ln.strip() for ln in out.split("This removes what setup.sh created here:")[1].split("(dry run")[0].splitlines() if ln.strip().startswith("- ")]
    home_ = env["HOME"]
    assert listed == ["- 1 Kiro Crew members, those still in the workspace vstatd: embedded-quality",
                      f"- the Kiro Crew workspace vstatd, if it still points to {home_}/workplace/vstatd",
                      f"- 1 agent templates in {home_}/.kiro/agents/: embedded-architect",
                      "- and puts back 1 agent templates it replaced: embedded-developer",
                      f"- the knowledge copy in {home_}/workplace/vstatd/knowledge: every file at a path knowledge/"
                      " has, whatever it holds now"]  # team_home recorded with no file list: an earlier setup's copy
    assert "the app vstatd-team" not in out and "(dry run: nothing removed)" in out
    for missing in ("vstatd-build:arm64", "vstatd-standin-sysroot", "「AI-DLC 团队」", "~/.npm"):  # left, and said so
        assert missing in out, missing
    assert "whatever it holds now" in out  # an earlier setup's copy: no record of the files
    assert calls(home) == []  # a dry run asks Kiro Crew nothing

    home["state"].unlink()
    for value in ("trust", "consent", "ui_dist"):
        run_py(SCRIPTS / "state.py", "add", "created", value, env=env)
    run_py(SCRIPTS / "state.py", "add", "found", "app", env=env)  # installed before setup: it stays
    out = subprocess.run(sh, capture_output=True, text=True, env=env).stdout
    assert "nothing of the app vstatd-team itself: it was installed before setup.sh and stays" in out
    assert "keeps the session-approval consent setup.sh sent" in out
    assert "the app vstatd-team's entry in Kiro Crew's trusted apps, which setup.sh added" in out
    assert "app/ui/dist (setup.sh built the board), once the app is gone" in out and "node_modules (" not in out


def knowledge_tree(root):
    for rel, text in (("a.md", "a\n"), ("facts/b.yaml", "b: 1\n"), ("tools/check.py", "x\n"), (".DS_Store", "")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def test_the_knowledge_copy_never_replaces_or_deletes_a_file_setup_did_not_write(home):
    env, src = home["env"], knowledge_tree(home["tmp"] / "knowledge")
    team = home["home"] / "workplace" / "vstatd"
    dst = team / "knowledge"
    k = lambda *a: run_py(SCRIPTS / "knowledge.py", *a, src, dst, env=env)  # noqa: E731

    assert k("plan").returncode == 0 and not dst.exists() and not home["state"].exists()
    assert k("install").returncode == 0
    assert sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()) == ["a.md", "facts/b.yaml"]
    state = json.loads(home["state"].read_text())
    assert state["created"] == ["team_home", "knowledge_dir"]
    assert sorted(state["knowledge_files"]) == ["a.md", "facts/b.yaml"]

    (dst / "alice-notes.md").write_text("mine\n", encoding="utf-8")  # added after setup
    (dst / "a.md").write_text("edited by alice\n", encoding="utf-8")
    r = k("install")  # an edited copy stops it: nothing is changed
    assert r.returncode == 1 and "a.md" in r.stderr and (dst / "a.md").read_text() == "edited by alice\n"
    (dst / "a.md").write_text("a\n", encoding="utf-8")
    (src / "facts" / "b.yaml").unlink()  # the scenario no longer has it: the unchanged copy goes
    (src / "c.md").write_text("c\n", encoding="utf-8")
    assert k("install").returncode == 0 and not (dst / "facts").exists() and (dst / "c.md").exists()
    assert (dst / "alice-notes.md").read_text() == "mine\n"

    (dst / "c.md").write_text("alice changed it\n", encoding="utf-8")
    out = k("remove").stdout
    assert "- 1 files of the knowledge copy" in out and f"! kept {dst / 'c.md'}: changed since setup copied it" in out
    assert f"! kept {dst}: it holds files setup did not copy there" in out
    assert sorted(p.name for p in dst.iterdir()) == ["alice-notes.md", "c.md"]
    assert "knowledge_files" not in json.loads(home["state"].read_text())


def test_a_knowledge_folder_that_was_there_before_setup_is_not_overwritten(home):
    env, src = home["env"], knowledge_tree(home["tmp"] / "knowledge")
    dst = home["home"] / "workplace" / "vstatd" / "knowledge"
    dst.mkdir(parents=True)
    (dst / "a.md").write_text("alice's own a.md\n", encoding="utf-8")
    (dst / "other.md").write_text("alice's\n", encoding="utf-8")
    r = run_py(SCRIPTS / "knowledge.py", "install", src, dst, env=env)
    assert r.returncode == 1 and "  a.md" in r.stderr and not home["state"].exists()
    assert sorted(p.name for p in dst.iterdir()) == ["a.md", "other.md"]
    (dst / "a.md").unlink()
    assert run_py(SCRIPTS / "knowledge.py", "install", src, dst, env=env).returncode == 0
    assert "created" not in json.loads(home["state"].read_text())  # the folders were there: not setup's
    out = run_py(SCRIPTS / "knowledge.py", "remove", src, dst, env=env).stdout
    assert "- 2 files" in out and sorted(p.name for p in dst.iterdir()) == ["other.md"]


def test_an_earlier_setups_copy_is_taken_as_setups_where_the_scenario_has_the_file(home):
    env, src = home["env"], knowledge_tree(home["tmp"] / "knowledge")
    dst = home["home"] / "workplace" / "vstatd" / "knowledge"
    dst.mkdir(parents=True)
    (dst / "a.md").write_text("an older a.md\n", encoding="utf-8")  # an earlier setup's copy, with no file record
    (dst / "alice.md").write_text("mine\n", encoding="utf-8")
    run_py(SCRIPTS / "state.py", "add", "created", "team_home", env=env)
    assert run_py(SCRIPTS / "knowledge.py", "install", src, dst, env=env).returncode == 0
    assert (dst / "a.md").read_text() == "a\n" and (dst / "alice.md").exists()
    assert sorted(json.loads(home["state"].read_text())["knowledge_files"]) == ["a.md", "facts/b.yaml"]


def test_install_team_records_the_knowledge_source_and_its_id_before_it_confirms(home):
    sources = []
    crew(home, sources=sources, **{"POST /api/knowledge/sources": {"source": {"id": "k9", "name": "vstatd"}}})
    r = subprocess.run(["bash", str(SCRIPTS / "install-team.sh")], capture_output=True, text=True, env=home["env"])
    assert r.returncode == 1 and "error:" in r.stderr  # the stand-in refuses the confirm
    state = json.loads(home["state"].read_text())
    assert "knowledge" in state["created"] and state["knowledge_id"] == ["k9"]
    assert ["POST", "/api/knowledge/sources/k9/confirm", "{}"] in calls(home)


def run_cleanup(rig):
    return subprocess.run(["bash", str(SAMPLE / "cleanup.sh")], input="remove\n", capture_output=True, text=True,
                          env=rig["env"])


def test_cleanup_removes_only_what_is_still_setups_and_keeps_the_record_when_a_step_fails(home):
    env, h = home["env"], home["home"]
    knowledge = h / "workplace" / "vstatd" / "knowledge"
    assert run_py(SCRIPTS / "knowledge.py", "install", SAMPLE / "knowledge", knowledge, env=env).returncode == 0
    for key, value in (("created", "app"), ("created", "sample_record"), ("created", "trust"),
                       ("created", "workspace"), ("created", "knowledge"), ("knowledge_id", "k1"),
                       ("members", "embedded-quality"), ("members", "embedded-developer")):
        run_py(SCRIPTS / "state.py", "add", key, value, env=env)
    app_data = h / ".kiro" / "crew" / "apps" / "vstatd-team" / "data"
    app_data.mkdir(parents=True)
    (app_data / "runs.json").write_text("{}\n", encoding="utf-8")
    crew(home, apps={"name": "vstatd-team"}, trusted=["vstatd-team", "other-app"],
         agents=[{"name": "embedded-quality", "kiro_agent": "embedded-quality", "workspace": "vstatd"},
                 {"name": "embedded-developer", "kiro_agent": "embedded-developer", "workspace": "alice"}],
         sources=[{"id": "k2", "name": "vstatd", "uri": str(knowledge)}],  # re-created by alice: not setup's
         workspaces=[{"name": "vstatd", "path": "/Users/alice/elsewhere"}],
         refuse=["/api/agents/embedded-quality"],  # Kiro Crew answers the DELETE, but the member is still listed
         **{"POST /api/apps/vstatd-team/sessions/cleanup": {"ok": True, "sessions": 3, "folders": 1,
                                                             "kept_runs": ["r1"]}})  # an older app ignores "all"

    first = run_cleanup(home)
    assert first.returncode == 1, first.stdout + first.stderr
    assert "the app's sessions were not all removed" in first.stdout and "Not everything was removed" in first.stdout
    assert "member embedded-quality not removed" in first.stdout and "run setup.sh to update it" in first.stdout
    log = calls(home)
    assert ["POST", "/api/apps/vstatd-team/sessions/cleanup", '{"all": true}'] in log
    deleted = [c[1] for c in log if c[0] == "DELETE"]
    assert deleted == ["/api/agents/embedded-quality"]  # not the app (its sessions are still there), nor alice's
    state = json.loads(home["state"].read_text())
    assert state == {"created": ["app", "sample_record", "trust"], "members": ["embedded-quality"]}  # what is left
    assert (app_data / "runs.json").exists() and not knowledge.exists()

    answers = json.loads(home["kc"].read_text())
    answers["POST /api/apps/vstatd-team/sessions/cleanup"] = {"ok": True, "sessions": 3, "folders": 1, "failed": 0,
                                                              "kept_runs": []}
    answers["refuse"] = []
    home["kc"].write_text(json.dumps(answers), encoding="utf-8")
    second = run_cleanup(home)
    assert second.returncode == 0, second.stdout + second.stderr
    for line in ("app removed", "trust removed", "member embedded-quality removed"):
        assert line in second.stdout, line
    deleted = [c[1] for c in calls(home)[len(log):] if c[0] == "DELETE"]
    assert deleted == ["/api/apps/vstatd-team", "/api/security/trusted-apps/vstatd-team",
                       "/api/agents/embedded-quality"]
    assert json.loads(home["kc"].read_text())["/api/security/trusted-apps"]["apps"] == ["other-app"]
    assert not home["state"].exists() and not app_data.parent.exists()


@pytest.fixture
def root(tmp_path):
    """This scenario's folder for setup.sh and cleanup.sh to run in: their own copies, the rest linked, an empty app/ui
    and a stand-in app/scripts/dev-install.sh, so that neither builds the board nor removes app/ui/ here."""
    r = tmp_path / "root"
    (r / "app" / "scripts").mkdir(parents=True)
    (r / "app" / "ui").mkdir()
    for name in ("setup.sh", "cleanup.sh"):
        shutil.copyfile(SAMPLE / name, r / name)
    for name in ("scripts", "agents", "vendor", "knowledge"):
        (r / name).symlink_to(SAMPLE / name)
    dev = r / "app" / "scripts" / "dev-install.sh"
    dev.write_text("#!/bin/sh\necho '{\"started\": true}'\n", encoding="utf-8")
    dev.chmod(0o755)
    return r


def sh(rig, root, script, *args, answer="remove\n"):
    return subprocess.run(["bash", str(root / script), *args], input=answer, capture_output=True, text=True,
                          env=rig["env"])


def record(rig, *pairs):
    for key, value in pairs:
        run_py(SCRIPTS / "state.py", "add", key, value, env=rig["env"])


def app_data(rig):
    d = rig["home"] / ".kiro" / "crew" / "apps" / "vstatd-team" / "data"
    d.mkdir(parents=True)
    (d / "runs.json").write_text("{}\n", encoding="utf-8")
    return d


def changes(rig):
    return [c for c in calls(rig) if c[0] != "GET"]


def test_cleanup_stops_and_keeps_everything_when_the_owner_api_refuses_this_shell(home, root):
    data = app_data(home)
    record(home, ("created", "app"), ("created", "sample_record"), ("created", "consent"),
           ("members", "embedded-quality"), ("created", "workspace"))
    before = home["state"].read_text()
    crew(home, apps={"name": "vstatd-team"}, up=["/api/health"])  # Kiro Crew runs; this shell gets no token
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "refused this shell as the dashboard owner" in r.stdout
    assert home["state"].read_text() == before and (data / "runs.json").exists()
    assert changes(home) == []


def test_cleanup_keeps_the_app_its_data_and_its_trust_while_kiro_crew_does_not_say_whether_they_are_there(home, root):
    data = app_data(home)
    record(home, ("created", "app"), ("created", "sample_record"), ("created", "consent"))
    crew(home, apps={"name": "vstatd-team"}, fail=["/api/apps/vstatd-team"])
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Kiro Crew did not say whether the app vstatd-team is installed" in r.stdout
    assert json.loads(home["state"].read_text())["created"] == ["app", "sample_record", "consent"]
    assert (data / "runs.json").exists() and changes(home) == []  # no sessions/cleanup, no uninstall

    home["state"].unlink()  # an app installed before setup: its trust entry and the board's build
    record(home, ("found", "app"), ("created", "trust"), ("created", "ui_dist"))
    (root / "app" / "ui" / "dist").mkdir()
    crew(home, apps={"name": "vstatd-team"}, trusted=["vstatd-team"],
         fail=["/api/apps/vstatd-team", "/api/security/trusted-apps"])
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Kiro Crew did not list its trusted apps" in r.stdout
    assert json.loads(home["state"].read_text()) == {"created": ["trust", "ui_dist"]}
    assert (root / "app" / "ui" / "dist").is_dir() and changes(home) == []


def test_cleanup_exits_1_and_keeps_the_record_when_kiro_crew_is_not_running(home, root):
    record(home, ("created", "app"), ("members", "embedded-quality"))
    before = home["state"].read_text()
    crew(home, up=[])
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 1 and "Kiro Crew is not running" in r.stdout
    assert home["state"].read_text() == before and changes(home) == []


def sign_in_gateway(rig):
    """Kiro Crew LTS signed out: its sign-in gateway answers /api/health and a 404 to every other path, and kcapi.sh,
    with an old cookie in its jar, prints that 404 body and exits 0"""
    rig["kc"].write_text(json.dumps({"/api/health": {"ok": True}}), encoding="utf-8")


def test_cleanup_removes_nothing_while_kiro_crew_answers_a_404_to_every_path_but_its_health(home, root):
    data = app_data(home)
    record(home, ("created", "app"), ("created", "sample_record"), ("created", "consent"))
    before = home["state"].read_text()
    sign_in_gateway(home)
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "refused this shell as the dashboard owner" in r.stdout
    assert home["state"].read_text() == before and (data / "runs.json").exists()
    assert changes(home) == []


def test_cleanup_keeps_the_apps_data_and_record_when_kiro_crew_does_not_answer_after_the_uninstall(home, root):
    data = app_data(home)
    record(home, ("created", "app"), ("created", "sample_record"), ("created", "consent"))
    crew(home, apps={"name": "vstatd-team"}, fail_get={"/api/apps/vstatd-team": [2]},  # the check after the DELETE
         **{"POST /api/apps/vstatd-team/sessions/cleanup": {"ok": True, "failed": 0, "kept_runs": []}})
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "did not say whether the app vstatd-team is installed: its data" in r.stdout
    assert [c[1] for c in changes(home)][-1] == "/api/apps/vstatd-team"  # the DELETE went out
    assert json.loads(home["state"].read_text())["created"] == ["app", "sample_record", "consent"]
    assert (data / "runs.json").exists()


@pytest.mark.parametrize("answer", [{"error": "502 Bad Gateway"}, "<html>502 Bad Gateway</html>"])
def test_cleanup_keeps_the_app_when_its_sessions_cleanup_answers_an_error(home, root, answer):
    data = app_data(home)
    record(home, ("created", "app"), ("created", "sample_record"))
    crew(home, apps={"name": "vstatd-team"}, **{"POST /api/apps/vstatd-team/sessions/cleanup": answer})
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the app's sessions were not all removed" in r.stdout and "run setup.sh to update it" not in r.stdout
    assert [c[1] for c in changes(home)] == ["/api/apps/vstatd-team/sessions/cleanup"]  # no disable, no uninstall
    assert json.loads(home["state"].read_text())["created"] == ["app", "sample_record"]
    assert (data / "runs.json").exists()


@pytest.mark.parametrize("runs", ["going", "unlisted"])
def test_cleanup_removes_nothing_while_a_run_is_still_going_or_the_app_does_not_list_its_runs(home, root, runs):
    data = app_data(home)
    knowledge = home["home"] / "workplace" / "vstatd" / "knowledge"
    assert run_py(SCRIPTS / "knowledge.py", "install", SAMPLE / "knowledge", knowledge, env=home["env"]).returncode == 0
    record(home, ("created", "app"), ("created", "sample_record"), ("created", "consent"),
           ("members", "embedded-quality"))
    before = home["state"].read_text()
    listed = {"runs": [{"id": "r2", "status": "reviewing"}, {"id": "r1", "status": "done"}]}  # r1 signed off
    crew(home, apps={"name": "vstatd-team"},
         agents=[{"name": "embedded-quality", "kiro_agent": "embedded-quality", "workspace": "vstatd"}],
         **({"/api/apps/vstatd-team/runs": listed} if runs == "going" else {"fail": ["/api/apps/vstatd-team/runs"]}),
         **{"POST /api/apps/vstatd-team/sessions/cleanup": {"ok": True, "failed": 0, "kept_runs": []}})
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 1, r.stdout + r.stderr
    said = ("run r2 is still going: stop it on the board, then run cleanup.sh again" if runs == "going"
            else "the app vstatd-team did not list its runs")
    assert said in r.stdout and "Nothing removed" in r.stdout
    assert changes(home) == []  # no sessions cleanup, no uninstall, no member removed
    assert home["state"].read_text() == before and (data / "runs.json").exists() and knowledge.is_dir()


@pytest.mark.parametrize("runs", ["going", "unlisted"])
def test_cleanup_removes_nothing_while_a_run_of_an_app_installed_before_setup_is_going(home, root, runs):
    data = app_data(home)
    knowledge = home["home"] / "workplace" / "vstatd" / "knowledge"
    assert run_py(SCRIPTS / "knowledge.py", "install", SAMPLE / "knowledge", knowledge, env=home["env"]).returncode == 0
    agents = home["home"] / ".kiro" / "agents"
    agents.mkdir(parents=True)
    (agents / "embedded-quality-agent.json").write_text("{}\n", encoding="utf-8")  # the template its roles run
    record(home, ("found", "app"), ("created", "trust"), ("created", "consent"),
           ("templates", "embedded-quality-agent"))
    before, copy = home["state"].read_text(), sorted(p for p in knowledge.rglob("*") if p.is_file())
    crew(home, apps={"name": "vstatd-team"}, trusted=["vstatd-team"],
         **({"/api/apps/vstatd-team/runs": {"runs": [{"id": "r2", "status": "reviewing"}]}} if runs == "going"
            else {"fail": ["/api/apps/vstatd-team/runs"]}))
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 1, r.stdout + r.stderr
    assert ("run r2 is still going" if runs == "going" else "did not list its runs") in r.stdout
    assert "Nothing removed" in r.stdout and changes(home) == []  # not even the trust entry
    assert home["state"].read_text() == before and (data / "runs.json").exists()
    assert (agents / "embedded-quality-agent.json").exists() and copy
    assert sorted(p for p in knowledge.rglob("*") if p.is_file()) == copy  # the knowledge copy its roles read


def test_cleanup_keeps_a_file_it_cannot_read_or_remove_and_says_what_is_left(home, root):
    knowledge = home["home"] / "workplace" / "vstatd" / "knowledge"
    assert run_py(SCRIPTS / "knowledge.py", "install", SAMPLE / "knowledge", knowledge, env=home["env"]).returncode == 0
    copied = json.loads(home["state"].read_text())["knowledge_files"]
    rel = sorted(copied)[0]
    agents = home["home"] / ".kiro" / "agents"
    agents.mkdir(parents=True)
    (agents / "embedded-quality-agent.json").write_text("{}\n", encoding="utf-8")
    record(home, ("templates", "embedded-quality-agent"))
    crew(home)
    (knowledge / rel).chmod(0o000)  # e.g. alice made it unreadable
    agents.chmod(0o555)  # and the templates' folder read-only
    try:
        r = sh(home, root, "cleanup.sh")
    finally:
        (knowledge / rel).chmod(0o644)
        agents.chmod(0o755)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Traceback" not in r.stdout + r.stderr
    assert f"! kept {knowledge / rel}: could not remove it (Permission denied)" in r.stdout
    assert "! kept embedded-quality-agent: could not remove it (Permission denied)" in r.stdout
    assert "Not everything was removed" in r.stdout and "Not removed:" in r.stdout  # the summary and the bench note
    state = json.loads(home["state"].read_text())
    assert state["knowledge_files"] == {rel: copied[rel]} and state["templates"] == ["embedded-quality-agent"]
    assert {"team_home", "knowledge_dir"} <= set(state["created"])
    assert sorted(p.relative_to(knowledge).as_posix() for p in knowledge.rglob("*") if p.is_file()) == [rel]

    again = sh(home, root, "cleanup.sh")  # fixed: the next cleanup removes what is left
    assert again.returncode == 0, again.stdout + again.stderr
    assert not home["state"].exists() and not knowledge.parent.exists()
    assert not (agents / "embedded-quality-agent.json").exists()


def test_cleanup_removes_the_app_and_its_sessions_once_every_run_has_ended(home, root):
    data = app_data(home)
    record(home, ("created", "app"), ("created", "sample_record"), ("created", "consent"))
    crew(home, apps={"name": "vstatd-team"},
         **{"/api/apps/vstatd-team/runs": {"runs": [{"id": "r3", "status": "stopped"}, {"id": "r2", "status": "failed"},
                                                     {"id": "r1", "status": "done"}]},  # r1 signed off: removed too
            "POST /api/apps/vstatd-team/sessions/cleanup": {"ok": True, "failed": 0, "kept_runs": []}})
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    log = calls(home)
    asked = log.index(["GET", "/api/apps/vstatd-team/runs"])
    assert asked < log.index(["POST", "/api/apps/vstatd-team/sessions/cleanup", '{"all": true}'])  # asked first
    assert [c[1] for c in changes(home)] == ["/api/apps/vstatd-team/sessions/cleanup", "/api/apps/vstatd-team/disable",
                                             "/api/apps/vstatd-team"]
    assert "app removed" in r.stdout and not data.parent.exists() and not home["state"].exists()


def test_cleanup_removes_the_knowledge_source_and_the_workspace_that_are_still_setups(home, root):
    team = home["home"] / "workplace" / "vstatd"
    record(home, ("created", "knowledge"), ("knowledge_id", "k1"), ("created", "workspace"))
    crew(home, sources=[{"id": "k1", "name": "vstatd", "uri": "/Users/alice/elsewhere"}, {"id": "k2", "name": "x"}],
         workspaces=[{"name": "vstatd", "path": str(team)}, {"name": "alice", "path": "/Users/alice"}])
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "knowledge source vstatd removed" in r.stdout and "workspace vstatd removed" in r.stdout
    assert [c[1] for c in changes(home)] == ["/api/knowledge/sources/k1", "/api/workspaces/vstatd"]  # by its id
    assert not home["state"].exists()

    # recorded with no id (the reply to its POST had none): the source of that name on the copy, not another
    record(home, ("created", "knowledge"))
    crew(home, sources=[{"id": "k7", "name": "vstatd", "uri": "/Users/alice/elsewhere"},
                        {"id": "k8", "name": "vstatd", "uri": str(team / "knowledge")}])
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    assert [c[1] for c in changes(home)][-1:] == ["/api/knowledge/sources/k8"]
    assert [s["id"] for s in json.loads(home["kc"].read_text())["/api/knowledge/sources"]["sources"]] == ["k7"]


@pytest.mark.parametrize("listed", [{"apps": ["vstatd-team", "other-app"]},
                                    {"apps": ["other-app"], "ineffective": ["vstatd-team"]}])
def test_cleanup_leaves_an_app_installed_before_setup_and_removes_the_trust_setup_added(home, root, listed):
    data = app_data(home)
    record(home, ("found", "app"), ("created", "trust"), ("created", "consent"), ("created", "ui_dist"))
    (root / "app" / "ui" / "dist").mkdir()
    crew(home, apps={"name": "vstatd-team"}, **{"/api/security/trusted-apps": listed})  # stored, in effect or not
    r = sh(home, root, "cleanup.sh")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "trust removed" in r.stdout and "kept app/ui/dist: the app vstatd-team stays installed" in r.stdout
    assert [c[1] for c in changes(home)] == ["/api/security/trusted-apps/vstatd-team"]  # not the app
    after = json.loads(home["kc"].read_text())["/api/security/trusted-apps"]
    assert "vstatd-team" not in after["apps"] + after.get("ineffective", [])
    assert (root / "app" / "ui" / "dist").is_dir() and (data / "runs.json").exists() and not home["state"].exists()


def test_cleanup_of_an_earlier_setups_copy_removes_the_scenarios_paths_whatever_they_hold(home):
    env, src = home["env"], knowledge_tree(home["tmp"] / "knowledge")
    dst = home["home"] / "workplace" / "vstatd" / "knowledge"
    (dst / "facts").mkdir(parents=True)
    (dst / "a.md").write_text("an older a.md\n", encoding="utf-8")  # an earlier setup's copy, with no file record
    (dst / "facts" / "b.yaml").write_text("b: 1\n", encoding="utf-8")
    (dst / "alice.md").write_text("mine\n", encoding="utf-8")
    record(home, ("created", "team_home"))
    out = run_py(SCRIPTS / "knowledge.py", "remove", src, dst, env=env).stdout
    assert "- 2 files of the knowledge copy" in out and f"! kept {dst}: it holds files setup did not copy there" in out
    assert sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*")) == ["alice.md"]


def test_the_knowledge_copy_neither_writes_nor_deletes_through_a_symbolic_link(home):
    env, src = home["env"], knowledge_tree(home["tmp"] / "knowledge")
    dst = home["home"] / "workplace" / "vstatd" / "knowledge"
    k = lambda *a: run_py(SCRIPTS / "knowledge.py", *a, src, dst, env=env)  # noqa: E731
    assert k("install").returncode == 0
    mine = home["home"] / "my docs"  # alice's own folder, with the same bytes as setup's copies
    mine.mkdir()
    (mine / "b.yaml").write_text("b: 1\n", encoding="utf-8")
    (mine / "a.md").write_text("a\n", encoding="utf-8")
    shutil.rmtree(dst / "facts")
    (dst / "facts").symlink_to(mine)  # a copied subfolder replaced by a link: b.yaml has a symlinked parent
    (dst / "a.md").unlink()
    (dst / "a.md").symlink_to(mine / "a.md")  # a copied file replaced by a link
    outside = home["home"] / "workplace" / "vstatd" / "alice.md"
    outside.write_text("mine\n", encoding="utf-8")
    state = json.loads(home["state"].read_text())
    state["knowledge_files"]["../alice.md"] = hashlib.sha256(b"mine\n").hexdigest()  # a path out of the copy
    home["state"].write_text(json.dumps(state), encoding="utf-8")

    (src / "facts" / "b.yaml").write_text("b: 2\n", encoding="utf-8")  # the scenario's update: not written there
    r = k("install")
    assert r.returncode == 0, r.stderr
    assert f"! kept {dst / 'facts/b.yaml'}: a symbolic link, under one, or outside the copy" in r.stdout
    assert (mine / "b.yaml").read_text() == "b: 1\n" and (dst / "a.md").is_symlink()

    state = json.loads(home["state"].read_text())
    state.setdefault("knowledge_files", {}).update({"facts/b.yaml": hashlib.sha256(b"b: 1\n").hexdigest(),
                                                   "a.md": hashlib.sha256(b"a\n").hexdigest(),
                                                   "../alice.md": hashlib.sha256(b"mine\n").hexdigest()})
    home["state"].write_text(json.dumps(state), encoding="utf-8")  # as if recorded: remove must not follow them
    r = k("remove")
    assert r.returncode == 0, r.stderr
    for rel in ("a.md", "facts/b.yaml", "../alice.md"):
        assert f"! kept {dst / rel}: a symbolic link, under one, or outside the copy" in r.stdout, rel
    assert (mine / "b.yaml").read_text() == "b: 1\n" and (mine / "a.md").read_text() == "a\n"
    assert (dst / "a.md").is_symlink() and (dst / "facts").is_symlink() and outside.read_text() == "mine\n"


def setup_crew(rig, **kw):
    """Kiro Crew for a setup.sh that runs to the end: the knowledge source is there and indexed"""
    crew(rig, sources=[{"name": "vstatd", "sync_status": "synced", "spend": {"files_done": 3, "files_total": 3}}], **kw)


@pytest.mark.skipif(platform.system() != "Darwin", reason="setup.sh runs on macOS")
def test_setup_records_what_it_creates_and_finds_an_app_trust_and_build_that_were_there(home, root):
    setup_crew(home)  # nothing there yet
    r = sh(home, root, "setup.sh", "--consent-session-approval", answer="")
    assert r.returncode == 0, r.stdout + r.stderr
    state = json.loads(home["state"].read_text())
    assert {"app", "trust", "ui_node_modules", "ui_dist", "consent", "sample_record"} <= set(state["created"])
    assert "found" not in state
    sample = home["home"] / ".kiro" / "crew" / "apps" / "vstatd-team" / "data" / "sample.json"
    assert json.loads(sample.read_text()) == {"sample": str(root.resolve())}

    home["state"].unlink()
    shutil.rmtree(home["home"])
    home["home"].mkdir()
    for d in ("node_modules", "dist"):
        (root / "app" / "ui" / d).mkdir()
    setup_crew(home, apps={"name": "vstatd-team"},  # installed and trusted (stored, not in effect) before setup
               **{"/api/security/trusted-apps": {"apps": [], "ineffective": ["vstatd-team"]}})
    r = sh(home, root, "setup.sh", answer="n\n")
    assert r.returncode == 0, r.stdout + r.stderr
    state = json.loads(home["state"].read_text())
    assert state["found"] == ["app"] and state["created"] == ["sample_record", "team_home", "knowledge_dir"]


@pytest.mark.skipif(platform.system() != "Darwin", reason="setup.sh runs on macOS")
@pytest.mark.parametrize("failing", ["/api/apps/vstatd-team", "/api/security/trusted-apps"])
def test_setup_stops_before_it_records_anything_when_kiro_crew_does_not_say_what_is_there(home, root, failing):
    setup_crew(home, apps={"name": "vstatd-team"}, fail=[failing])
    r = sh(home, root, "setup.sh", "--consent-session-approval", answer="")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Kiro Crew did not" in r.stdout and "run setup.sh again" in r.stdout
    assert not home["state"].exists() and not (home["home"] / ".kiro").exists() and changes(home) == []


@pytest.mark.skipif(platform.system() != "Darwin", reason="setup.sh runs on macOS")
def test_setup_stops_while_kiro_crew_answers_a_404_to_every_path_but_its_health(home, root):
    sign_in_gateway(home)
    r = sh(home, root, "setup.sh", "--consent-session-approval", answer="")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "refused this shell as the dashboard owner" in r.stdout
    assert not home["state"].exists() and not (home["home"] / ".kiro").exists() and changes(home) == []
