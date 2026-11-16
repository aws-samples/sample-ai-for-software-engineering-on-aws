#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""The bypass hook: a Kiro `preToolUse` hook that refuses the tool calls an agent of this sample has no business making.

Defence in depth, not the boundary (scenario README, "Around the servers"): the MCP servers are the only path meant to
work, and a real team's build server holds no target key, no Docker access and no push credentials. This hook makes
the other paths fail too, as far as a check on the command text can. Command patterns are easy to get around, for
example by writing a script and running it; `../probe/` measures which variants it stops on each Kiro version.

Kiro passes the call as JSON on stdin (`tool_name`, `tool_input`); exit status 2 refuses it and stderr goes to the
agent, 0 lets it run. Refused:

- shell commands that reach the emulated target or the bench without the `bench` server: Docker (and Podman,
  nerdctl), `bench/cc1.sh` and `bench/console.py`, SSH, SCP, SFTP, rsync, netcat, socat or telnet to the target's
  forwarded port, and anything naming the bench's container, volumes or state folder;
- shell commands and file writes that touch the bench state (`$CC1_BENCH_STATE`, default `~/.cc1-bench`) or the
  results of the Kiro Crew app's runs (`~/workplace/vstatd-team/runs/<run>/results/`);
- `git push` and history rewrites: `push`, `rebase`, `reset --hard`, `filter-branch`, `filter-repo`, `update-ref`,
  `commit --amend`, `branch -D/-f`, `tag -f`, `reflog expire`, `gc --prune`, with options before the subcommand
  (`git -C <dir> push`), behind `env`, `sudo`, `command`, `exec`, `xargs`, `sh -c` and the like, and in compound
  commands.

Anything else runs. A hook that cannot read its input refuses (fail closed).
"""

import json
import os
import re
import shlex
import sys

BENCH_NAMES = ("cc1-bench", "cc1-run", "cc1-images", "cc1-sysroot", "cc1-br-")  # the bench's container, volumes
TARGET_PORT = "2222"  # QEMU's forwarded SSH port of the emulated CC-1 (bench/cc1.sh)
CONTAINER_TOOLS = ("docker", "podman", "nerdctl", "ctr", "crictl")
NET_TOOLS = ("ssh", "scp", "sftp", "rsync", "nc", "ncat", "netcat", "socat", "telnet")
BENCH_SCRIPTS = re.compile(r"(^|/)(cc1\.sh|console\.py)$")
# Words that run the rest of the line as a command.
WRAPPERS = ("env", "sudo", "doas", "command", "builtin", "exec", "nohup", "nice", "ionice", "time", "timeout",
            "stdbuf", "setsid", "xargs", "chronic", "unbuffer", "flock", "watch")
SHELLS = ("sh", "bash", "dash", "zsh", "ksh", "fish", "busybox")
GIT_GLOBAL_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env")
SPLIT = re.compile(r"&&|\|\||[;&|\n]|\$\(|`|\)|\(|\{|\}")


def home():
    return os.path.expanduser("~")


def protected_paths():
    state = os.environ.get("CC1_BENCH_STATE") or os.path.join(home(), ".cc1-bench")
    runs = os.path.join(home(), "workplace", "vstatd-team", "runs")
    return [os.path.normpath(state)], os.path.normpath(runs)


def refuse(why):
    print(f"refused by the sample's bypass hook (agents/hooks/guard.py): {why}. Use the build and bench MCP "
          "servers, or hand back to a person.", file=sys.stderr)
    return 2


def words(segment):
    """The words of one simple command, quotes and backslashes resolved as the shell would, as far as shlex can."""
    try:
        return shlex.split(segment, posix=True)
    except ValueError:  # an unbalanced quote: judge the raw words, quotes removed
        return re.sub(r"[\"'\\]", "", segment).split()


def unwrap(ws):
    """Drops variable assignments and wrapper words, so `env X=1 sudo -u u git push` is judged as `git push`."""
    with_value = {"sudo": ("-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"), "doas": ("-u", "-C"),
                  "nice": ("-n",), "ionice": ("-c", "-n"), "xargs": ("-I", "-n", "-L", "-P", "-d", "-a", "-E", "-s"),
                  "timeout": ("-s", "-k"), "watch": ("-n", "-d")}
    i = 0
    while i < len(ws):
        w, base = ws[i], os.path.basename(ws[i])
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w):
            i += 1
            continue
        if base not in WRAPPERS:
            break
        i += 1
        while i < len(ws) and ws[i].startswith("-") and ws[i] != "--":
            i += 2 if ws[i] in with_value.get(base, ()) else 1
        if i < len(ws) and ws[i] == "--":
            i += 1
        if base == "timeout" and i < len(ws) and re.fullmatch(r"[\d.]+[smhd]?", ws[i]):
            i += 1
        if base == "flock" and i < len(ws):
            i += 1  # the lock file
    return ws[i:]


def inner_scripts(ws):
    """The command strings a shell word runs: `sh -c '<script>'`, `bash -lc '<script>'`, `eval <script>`."""
    out = []
    if ws and os.path.basename(ws[0]) in SHELLS:
        for j, w in enumerate(ws[1:], 1):
            if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", w) and j + 1 < len(ws):
                out.append(ws[j + 1])
                break
    if ws and ws[0] == "eval":
        out.append(" ".join(ws[1:]))
    return out


def git_subcommand(ws):
    """`git` with its global options skipped: (subcommand, its arguments), or None if not git."""
    if not ws or os.path.basename(ws[0]) != "git":
        return None
    i = 1
    while i < len(ws) and ws[i].startswith("-"):
        opt = ws[i]
        i += 1
        if opt in GIT_GLOBAL_WITH_VALUE and i < len(ws):
            i += 1
    return (ws[i], ws[i + 1:]) if i < len(ws) else ("", [])


def git_refusal(sub, args):
    if sub == "push":
        return "git push"
    if sub in ("rebase", "filter-branch", "filter-repo", "update-ref", "replace"):
        return f"git {sub} rewrites history"
    if sub == "reset" and any(a in ("--hard", "--keep", "--merge") for a in args):
        return "git reset --hard"
    if sub == "commit" and "--amend" in args:
        return "git commit --amend rewrites history"
    if sub == "branch" and any(a in ("-D", "-f", "--force", "-M", "-C") or re.fullmatch(r"-[a-zA-Z]*[DfMC][a-zA-Z]*", a)
                               for a in args):
        return "git branch -D/-f"
    if sub == "tag" and any(a in ("-f", "--force", "-d", "--delete") for a in args):
        return "git tag -f/-d"
    if sub == "reflog" and args[:1] in (["expire"], ["delete"]):
        return "git reflog expire"
    if sub == "gc" and any(a.startswith("--prune") for a in args):
        return "git gc --prune"
    if sub == "config" and any(re.match(r"(alias\.|core\.(hooksPath|sshCommand)|url\.)", a, re.I) for a in args):
        return "git config of aliases, hooks or remotes"
    return None


def mentions_protected(text, states, runs):
    norm = text.replace("~", home()).replace("$HOME", home()).replace("${HOME}", home())
    for p in states:
        if p in norm or "CC1_BENCH_STATE" in text or ".cc1-bench" in text:
            return "the bench state"
    if re.search(re.escape(runs) + r"/[^/\s]+/results", norm) or re.search(r"vstatd-team/runs/[^/\s]+/results",
                                                                             norm):
        return "the check results of a run"
    return None


def judge_segment(seg, states, runs, depth=0):
    ws = unwrap(words(seg))
    if not ws:
        return None
    for script in inner_scripts(ws):
        if depth < 5:
            why = judge_command(script, states, runs, depth + 1)
            if why:
                return why
    cmd = os.path.basename(ws[0])
    if cmd in CONTAINER_TOOLS:
        return f"{cmd}: the agents reach the bench only through the bench server"
    if BENCH_SCRIPTS.search(ws[0]) or any(BENCH_SCRIPTS.search(w) for w in ws[1:2] if cmd in ("python3", "python",
                                                                                                  "bash", "sh")):
        return "the bench's own scripts (bench/cc1.sh, bench/console.py) are for the bench owner"
    if cmd in NET_TOOLS and (TARGET_PORT in " ".join(ws[1:]) or any(re.search(r"(^|@)(127\.0\.0\.1|localhost|::1|"
                                                                                  r"cc1)(:|$)", w) for w in ws[1:])):
        return f"{cmd} to the emulated target"
    g = git_subcommand(ws)
    if g:
        why = git_refusal(*g)
        if why:
            return why
    return None


def judge_command(command, states, runs, depth=0):
    if any(n in command for n in BENCH_NAMES):
        return "the bench's container or volumes"
    if re.search(r"(/dev/tcp/|/dev/udp/)[^/\s]+/" + TARGET_PORT, command):
        return "a connection to the emulated target"
    why = mentions_protected(command, states, runs)
    if why:
        return why
    for seg in SPLIT.split(command):
        why = judge_segment(seg, states, runs, depth)
        if why:
            return why
    return None


def judge(event):
    """The reason to refuse a tool call, or None. `event` is the hook's input."""
    states, runs = protected_paths()
    name = str(event.get("tool_name", ""))
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return "a tool call the hook cannot read"
    if name in ("shell", "execute_bash", "execute_cmd", "execute_pwsh"):
        command = tool_input.get("command")
        if not isinstance(command, str):
            return "a shell call without a command"
        return judge_command(command, states, runs)
    if name in ("write", "fs_write", "fs_append", "str_replace", "delete_file"):
        for key in ("path", "file_path", "target"):
            path = tool_input.get(key)
            if isinstance(path, str):
                full = os.path.normpath(os.path.join(event.get("cwd") or home(), os.path.expanduser(path)))
                why = mentions_protected(full, states, runs)
                if why:
                    return f"a write to {why}"
        return None
    return None


def main():
    try:
        event = json.loads(sys.stdin.read() or "{}")
        if not isinstance(event, dict):
            raise ValueError("not an object")
    except ValueError as e:
        return refuse(f"unreadable hook input ({e})")
    why = judge(event)
    return refuse(why) if why else 0


if __name__ == "__main__":
    sys.exit(main())
