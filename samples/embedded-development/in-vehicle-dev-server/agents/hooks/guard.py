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

- shell commands that reach the emulated target or the bench without the `bench` server: Docker (every `docker*`
  command), Podman, nerdctl, a container runtime's socket, `bench/cc1.sh` and `bench/console.py`, SSH, SCP, SFTP,
  rsync, netcat, socat or telnet to the target's forwarded port or to loopback, and anything naming the bench's
  container or volumes;
- shell commands and file writes that touch the bench state (`$CC1_BENCH_STATE`, default `~/.cc1-bench`) or the
  results of the Kiro Crew app's runs (`~/workplace/vstatd-team/runs/<run>/results/`);
- `git push` (also `send-pack`, `http-push`, `hub push`) and history rewrites: `rebase`, `reset --hard`,
  `filter-branch`, `filter-repo`, `update-ref`, `commit --amend`, `branch -D/-f`, `checkout -B`, `switch -C`,
  `tag -f/-d`, `reflog expire`, `gc --prune`, and aliases, hooks or remote URLs set with `git config` or `git -c`;
  with options before the subcommand (`git -C <dir> push`), behind `env`, `sudo`, `command`, `exec`, `xargs`,
  `sh -c`, `eval`, `find -exec`, `submodule foreach` and the like, in command substitutions and compound commands.

The command line is split at unquoted operators, so a commit message that mentions `git push` is no reason to
refuse. Anything else runs. Input the hook cannot read, and a tool it does not know, are refused (fail closed).
"""

import json
import os
import re
import shlex
import sys

# The bench's container and volumes, as names (not as the sysroot's mount path /opt/cc1-sysroot).
BENCH_NAMES = re.compile(r"(?<![\w./-])(cc1-bench[\w-]*|cc1-run|cc1-images|cc1-sysroot|cc1-br-[\w-]+)(?![\w-])")
SOCKETS = ("docker.sock", "podman.sock", "containerd.sock")
TARGET_PORT = "2222"  # QEMU's forwarded SSH port of the emulated CC-1 (bench/cc1.sh)
CONTAINER_TOOLS = ("docker", "podman", "nerdctl", "ctr", "crictl")  # and every docker-* command
GIT_LIKE = ("git", "hub")
NET_TOOLS = ("ssh", "scp", "sftp", "rsync", "nc", "ncat", "netcat", "socat", "telnet")
BENCH_SCRIPTS = re.compile(r"(^|/)(cc1\.sh|console\.py)$")
# Words that run the rest of the line as a command.
WRAPPERS = ("{", "}", "!", "if", "then", "else", "elif", "do", "while", "until",  # shell words before a command
            "env", "sudo", "doas", "command", "builtin", "exec", "nohup", "nice", "ionice", "time", "timeout",
            "stdbuf", "setsid", "xargs", "chronic", "unbuffer", "flock", "watch")
CONFIG_KEYS = (r"(alias\.|core\.(hookspath|sshcommand|gitproxy)|url\.|"
               r"remote\.[^=]*\.(url|pushurl|receivepack))")
SHELLS = ("sh", "bash", "dash", "zsh", "ksh", "fish", "busybox")
GIT_GLOBAL_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env")
OPERATORS = set(";&|()<>\n")
SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")  # judged even inside quotes: "$(git push)" runs


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


def segments(command):
    """The simple commands of a command line, as lists of words: split at unquoted ; & | ( ) < > and newlines, with
    quotes and backslashes resolved as the shell would, as far as shlex can. An unbalanced quote falls back to a
    split that ignores quotes, which errs on the side of refusing."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    out, cur = [], []
    try:
        for tok in lex:
            if tok and set(tok) <= OPERATORS:
                out.append(cur)
                cur = []
            else:
                cur.append(tok)
    except ValueError:
        raw = re.sub(r"[\"'\\]", "", command)
        return [seg.split() for seg in re.split(r"[;&|()<>\n]", raw)]
    out.append(cur)
    return [seg for seg in out if seg]


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
        if base == "command" and i + 1 < len(ws) and ws[i + 1] in ("-v", "-V"):
            return []  # `command -v x` only looks x up
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
    if "foreach" in ws[1:]:  # git submodule foreach <command>
        out.append(" ".join(ws[ws.index("foreach") + 1:]))
    for flag in ("-exec", "-execdir", "-ok", "-okdir"):  # find ... -exec <command> ;
        if flag in ws[1:]:
            rest = ws[ws.index(flag) + 1:]
            out.append(" ".join(w for w in rest if w not in (";", "+", "{}")))
    return out


def git_subcommand(ws):
    """`git` with its global options skipped: (subcommand, its arguments), or None if not git."""
    if not ws or os.path.basename(ws[0]) not in GIT_LIKE:
        return None
    i, config = 1, []
    while i < len(ws) and ws[i].startswith("-"):
        opt = ws[i]
        i += 1
        if opt in GIT_GLOBAL_WITH_VALUE and i < len(ws):
            if opt in ("-c", "--config-env"):
                config.append(ws[i])
            i += 1
        elif opt.startswith(("--config-env=", "-c")) and len(opt) > 2:
            config.append(opt.split("=", 1)[-1] if opt.startswith("--") else opt[2:])
    return (ws[i], ws[i + 1:], config) if i < len(ws) else ("", [], config)


def git_refusal(sub, args, config=()):
    if any(re.match(CONFIG_KEYS, c, re.I) for c in config):
        return "git -c of aliases, hooks or remotes"
    if sub in ("push", "send-pack", "http-push"):
        return "git push"
    if sub in ("checkout", "switch") and any(a in ("-B", "-C", "--force-create") for a in args):
        return f"git {sub} -B/-C moves a branch"
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
    reading = any(a in ("--get", "--get-all", "--get-regexp", "-l", "--list", "--show-origin") for a in args)
    if sub == "config" and not reading and any(re.match(CONFIG_KEYS, a, re.I) for a in args):
        return "git config of aliases, hooks or remotes"
    return None


def mentions_protected(text, states, runs):
    norm = text.replace("~", home()).replace("$HOME", home()).replace("${HOME}", home())
    norm = re.sub(r"/{2,}", "/", re.sub(r"/(\./)+", "/", norm))
    for p in states:
        if p in norm or "CC1_BENCH_STATE" in text or ".cc1-bench" in text:
            return "the bench state"
    if re.search(re.escape(runs) + r"/[^/\s]+/results", norm) or re.search(r"vstatd-team/runs/[^/\s]+/results",
                                                                             norm):
        return "the check results of a run"
    return None


def judge_segment(ws, states, runs, depth=0):
    ws = unwrap(ws)
    if not ws:
        return None
    for script in inner_scripts(ws):
        if depth < 5:
            why = judge_command(script, states, runs, depth + 1)
            if why:
                return why
    cmd = os.path.basename(ws[0])
    if cmd in CONTAINER_TOOLS or cmd.startswith("docker"):
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
    if BENCH_NAMES.search(command) or any(k in command for k in SOCKETS):
        return "the bench's container or volumes, or a container runtime's socket"
    if re.search(r"(/dev/tcp/|/dev/udp/)[^/\s]+/" + TARGET_PORT, command):
        return "a connection to the emulated target"
    why = mentions_protected(command, states, runs)
    if why:
        return why
    if depth < 5:
        for m in SUBSTITUTION.finditer(command):
            why = judge_command(m.group(1) or m.group(2) or "", states, runs, depth + 1)
            if why:
                return why
    for ws in segments(command):
        why = judge_segment(ws, states, runs, depth)
        if why:
            return why
    return None


def judge(event):
    """The reason to refuse a tool call, or None. `event` is the hook's input. The hook is attached to the shell and
    to file writes only, so a call it does not recognise is refused."""
    states, runs = protected_paths()
    name = str(event.get("tool_name", ""))
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return "a tool call the hook cannot read"
    if name in ("shell", "execute_bash", "execute_cmd", "execute_pwsh"):
        command = tool_input.get("command")
        if not isinstance(command, str):
            return "a shell call without a command"
        return judge_command(command, states, runs)
    if name in ("write", "fs_write", "fs_append", "str_replace", "delete_file"):
        paths = [tool_input[k] for k in ("path", "file_path", "target") if isinstance(tool_input.get(k), str)]
        if not paths:
            return "a file write without a path the hook can read"
        for path in paths:
            full = os.path.normpath(os.path.join(event.get("cwd") or home(), os.path.expanduser(path)))
            for p in (full, os.path.realpath(full)):  # also through a link that points into a protected folder
                why = mentions_protected(p, states, runs)
                if why:
                    return f"a write to {why}"
        return None
    return f"a tool the hook does not know ({name or 'no tool name'})"


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
