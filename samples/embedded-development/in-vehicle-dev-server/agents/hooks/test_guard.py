#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Tests of the bypass hook on its own, without Kiro: python3 agents/hooks/test_guard.py

Each case is a tool call as Kiro passes it to a `preToolUse` hook. REFUSED must be refused, ALLOWED must run, and
GETS_THROUGH lists bypasses the hook does not stop, as a record of its limits: if one of them starts being refused,
move it to REFUSED. `../probe/probe.py` runs the same commands through a real Kiro session.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
GUARD = HERE / "guard.py"

REFUSED = [
    # git push and history rewrites, with options, wrappers, quoting and compound commands
    "git push", "git push --force origin main", "git -C /tmp/x push", "git -c user.name=x push origin HEAD",
    "/usr/bin/git push", "\\git push", '"git" "push"', "g\\it pu\\sh", "env GIT_TRACE=1 git push",
    "sudo -u build git push", "command git push", "exec git push", "nohup git push &", "timeout 30 git push",
    "xargs -I{} git push", "cd repo && git push", "make; git push", "true || git push", "echo x | git push",
    "(git push)", "{ git push; }", "$(git push)", "`git push`", "sh -c 'git push'", "bash -lc \"git push\"",
    "bash -c 'cd /tmp && git push origin main'", "eval git push", "git rebase -i HEAD~3", "git reset --hard HEAD~1",
    "git filter-branch --tree-filter x", "git update-ref refs/heads/main HEAD~1", "git commit --amend -m x",
    "git branch -D old", "git branch -f main HEAD~2", "git tag -f v1", "git reflog expire --all", "git gc --prune=now",
    "git config alias.p push", "git config core.hooksPath /tmp/h", "git -c alias.p=push p origin main",
    "git --config-env=alias.p=X p", "git -c remote.origin.pushurl=/tmp/x push", "git send-pack /tmp/r main",
    "git http-push https://example.com/r main", "git checkout -B main HEAD~1", "git switch -C main HEAD~1",
    "hub push", "git submodule foreach git push", "find . -name x -exec git push \\;", 'git commit -m "$(git push)"',
    "git --no-pager push", "GIT_DIR=/tmp/x/.git git push", "/bin/sh -c 'git push'", "busybox sh -c 'git push'",
    "sh -lc 'git push'", "true\ngit push", "true;\tgit push",
    # the bench without the bench server
    "docker exec cc1-bench ls /secrets", "docker run -v cc1-bench-secrets:/s alpine cat /s/id_ed25519",
    "docker ps", "/usr/bin/docker ps", "DOCKER_HOST=unix:///x docker ps", "docker-compose ps",
    "curl --unix-socket /var/run/docker.sock http://localhost/containers/json", "podman exec cc1-bench sh",
    "sudo docker cp cc1-bench:/secrets/id_ed25519 .",
    "ssh -p 2222 root@127.0.0.1", "scp -P 2222 vstatd root@localhost:/usr/bin/", "ssh root@127.0.0.1",
    "rsync -e 'ssh -p 2222' build/vstatd root@127.0.0.1:/usr/bin/", "nc 127.0.0.1 2222",
    "exec 3<>/dev/tcp/127.0.0.1/2222", "bench/cc1.sh ssh systemctl restart vstatd", "./bench/cc1.sh deploy x",
    "python3 bench/console.py approve 20261116-deploy-1 --digest abc123", "bash bench/cc1.sh replay --kind run",
    "ssh -p 2222 root@10.0.0.5", "ssh -oPort=2222 root@x", "socat - TCP:127.0.0.1:2222",
    "ls ~/.cc1-bench", "echo x > ${HOME}/.cc1-bench/x", "ln -s ~/.cc1-bench /tmp/b", "cp x ~/./.cc1-bench//a",
    "echo approved > ~/.cc1-bench/requests/x.json", "cat $HOME/.cc1-bench/lease.json",
    "echo PASS > ~/workplace/vstatd-team/runs/r11032637/results/static.json",
    "cp /tmp/forged.json ~/workplace/vstatd-team/runs/r1/results/unit.json",
]

ALLOWED = [
    "git status", "git add -A", "git commit -m 'F-008: justify the condition (VSTATD-IF p.7 §4.2)'",
    "git commit -m \"push the fix\"", "git log --oneline -5", "git log --grep=rebase", "git diff HEAD~1",
    "git show HEAD:src/supervisor.cpp", "git branch", "git switch -c fix/f008", "git reset src/main.cpp",
    "git stash", "git tag", "cmake -S . -B build -G Ninja", "ninja -C build vstatd_tests",
    "ctest --test-dir build --output-on-failure", "grep -rn entry.supervised src/", "ls knowledge/",
    "python3 knowledge/tools/check_knowledge.py --no-pdf", "cat knowledge/cc1-platform-notes.md | head -50",
    "echo done", "ssh -V", "rsync -a src/ /tmp/copy/", "git commit -m 'fix; git push later'",
    "git commit -m \"docs (docker not used)\"", "grep -rnE 'docker|podman' docs/", "grep -n 'pull\\|git push' x",
    "echo '(ssh to 127.0.0.1)'", "git reset --soft HEAD~1", "git branch -d merged", "git tag -l", "ls build/",
    "git config --get remote.origin.url", "rg 'TODO|FIXME' src", "ls /opt/cc1-sysroot/usr/include",
    "grep -rn CMAKE_SYSROOT cmake/", "git checkout -b fix/f021", "git switch main", "command -v docker", "which docker ssh",
]

# Known bypasses: the command text does not show what runs. The README says so; the real boundary is a build server
# without the target key, Docker access and push credentials.
GETS_THROUGH = [
    "printf 'git pu''sh' > /tmp/p.sh && sh /tmp/p.sh",  # the script names the command, not the line
    "python3 -c \"import subprocess; subprocess.run(['git', 'pu' + 'sh'])\"",
    "echo Z2l0IHB1c2g= | base64 -d | sh",
    "G=git; $G push",
    "sh <<< 'git push'", "echo 'git push' | sh", "$'\\x67it' push", "env -S 'git push'",
    "cd ~/workplace/vstatd-team/runs/r1 && echo PASS > results/static.json", "gh pr merge 1",
    "curl telnet://127.0.0.1:2222",
]

WRITES_REFUSED = ["~/.cc1-bench/requests/x.json", "{home}/workplace/vstatd-team/runs/r1/results/static.json"]
WRITES_ALLOWED = ["src/supervisor.cpp", "tests/test_supervisor.cpp", "{home}/workplace/vstatd-team/work/notes.md"]


def run(event, env=None):
    p = subprocess.run([sys.executable, GUARD], input=json.dumps(event), capture_output=True, text=True,
                       env={**os.environ, **(env or {})})
    return p.returncode, p.stderr


def shell(command):
    return {"hook_event_name": "preToolUse", "cwd": "/tmp", "tool_name": "shell", "tool_tags": ["shell", "@builtin"],
            "tool_input": {"command": command}}


class Guard(unittest.TestCase):
    def test_refused(self):
        for c in REFUSED:
            with self.subTest(c):
                rc, err = run(shell(c))
                self.assertEqual(rc, 2, c)
                self.assertIn("bypass hook", err)

    def test_allowed(self):
        for c in ALLOWED:
            with self.subTest(c):
                self.assertEqual(run(shell(c)), (0, ""), c)

    def test_known_bypasses_still_get_through(self):
        for c in GETS_THROUGH:
            with self.subTest(c):
                self.assertEqual(run(shell(c))[0], 0, f"now refused: move it to REFUSED: {c}")

    def test_writes(self):
        home = os.path.expanduser("~")
        for name in ("write", "fs_write", "str_replace"):
            for p in WRITES_REFUSED:
                with self.subTest((name, p)):
                    e = {"tool_name": name, "cwd": "/tmp", "tool_input": {"path": p.format(home=home)}}
                    self.assertEqual(run(e)[0], 2)
            for p in WRITES_ALLOWED:
                with self.subTest((name, p)):
                    e = {"tool_name": name, "cwd": "/tmp/repo", "tool_input": {"path": p.format(home=home)}}
                    self.assertEqual(run(e)[0], 0)
        e = {"tool_name": "write", "cwd": os.path.join(home, ".cc1-bench"), "tool_input": {"path": "approvals.json"}}
        self.assertEqual(run(e)[0], 2, "a relative path resolves against the session's folder")

    def test_the_bench_state_of_the_environment(self):
        with tempfile.TemporaryDirectory() as d:
            rc, _ = run(shell(f"echo x > {d}/lease.json"), {"CC1_BENCH_STATE": d})
            self.assertEqual(rc, 2)

    def test_a_write_through_a_link_into_the_bench_state(self):
        with tempfile.TemporaryDirectory() as d:
            state = pathlib.Path(d) / "state"
            state.mkdir()
            (pathlib.Path(d) / "link").symlink_to(state)
            e = {"tool_name": "write", "cwd": d, "tool_input": {"path": "link/lease.json"}}
            self.assertEqual(run(e, {"CC1_BENCH_STATE": str(state)})[0], 2)

    def test_unknown_tools_and_unreadable_input_are_refused(self):
        self.assertEqual(run({"tool_name": "read", "tool_input": {"path": "x"}})[0], 2, "not a tool the hook is on")
        self.assertEqual(run({"tool_input": {"command": "git push"}})[0], 2, "no tool name")
        self.assertEqual(run({"tool_name": "write", "tool_input": {"file": "~/.cc1-bench/x"}})[0], 2, "no path")
        p = subprocess.run([sys.executable, GUARD], input="not json", capture_output=True, text=True)
        self.assertEqual(p.returncode, 2, "fail closed")
        self.assertEqual(run({"tool_name": "shell", "tool_input": {}})[0], 2)
        self.assertEqual(run({"tool_name": "shell", "tool_input": "git push"})[0], 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
