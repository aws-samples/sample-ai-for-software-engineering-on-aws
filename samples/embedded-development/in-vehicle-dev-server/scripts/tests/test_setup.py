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
EXPERTS = {"embedded-developer": "aidlc-developer-agent", "embedded-architect": "aidlc-architect-agent",
           "embedded-quality": "aidlc-quality-agent", "embedded-architecture-reviewer": "aidlc-architecture-reviewer-agent"}
MEMBERS = list(EXPERTS)

KCAPI = """#!/usr/bin/env python3
import json, os, sys
method, path = sys.argv[1], sys.argv[2]
with open(os.environ["FAKE_KC_LOG"], "a") as f:
    f.write(json.dumps([method, path] + sys.argv[3:]) + "\\n")
answers = json.load(open(os.environ["FAKE_KC"]))
if method == "GET":
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
    print(json.dumps(answers.get(f"{method} {path}", {"error": "the stand-in refuses this"})))
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
                      f"- the knowledge copy in {home_}/workplace/vstatd/knowledge (files you added or changed stay)"]
    assert "the app vstatd-team" not in out and "(dry run: nothing removed)" in out
    for missing in ("vstatd-build:arm64", "vstatd-standin-sysroot", "「AI-DLC 团队」", "~/.npm"):  # left, and said so
        assert missing in out, missing
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
         **{"POST /api/apps/vstatd-team/sessions/cleanup": {"ok": True, "sessions": 3, "folders": 1, "failed": 1}})

    first = run_cleanup(home)
    assert first.returncode == 1, first.stdout + first.stderr
    assert "the app's sessions were not all removed" in first.stdout and "Not everything was removed" in first.stdout
    log = calls(home)
    assert ["POST", "/api/apps/vstatd-team/sessions/cleanup", '{"all": true}'] in log
    deleted = [c[1] for c in log if c[0] == "DELETE"]
    assert deleted == ["/api/agents/embedded-quality"]  # not the app (its sessions are still there), nor alice's
    state = json.loads(home["state"].read_text())
    assert state == {"created": ["app", "sample_record", "trust"]}  # what is left, for the next run
    assert (app_data / "runs.json").exists() and not knowledge.exists()

    answers = json.loads(home["kc"].read_text())
    answers["POST /api/apps/vstatd-team/sessions/cleanup"]["failed"] = 0
    home["kc"].write_text(json.dumps(answers), encoding="utf-8")
    second = run_cleanup(home)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "app removed" in second.stdout and "trust removed" in second.stdout
    deleted = [c[1] for c in calls(home)[len(log):] if c[0] == "DELETE"]
    assert deleted == ["/api/apps/vstatd-team", "/api/security/trusted-apps/vstatd-team"]
    assert json.loads(home["kc"].read_text())["/api/security/trusted-apps"]["apps"] == ["other-app"]
    assert not home["state"].exists() and not app_data.parent.exists()
