"""Git for a run: always ``git -C <dir> …`` as an async subprocess (never a shell), isolated from the user's git
config, hooks and signing. Layout: ``<root>/repo`` (base = the requirement commit), the run branch checked out in
``<root>/wt/_run`` (merges and test runs happen there), one branch + worktree per writing role in ``<root>/wt/<role>``.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import os
import re
import shutil
from pathlib import Path
from typing import Any

from .constants import GIT_BIN

AUTHOR = ("aidlc-team", "team@localhost")
# Appended to each run repo's .git/config, so the role agents' own commits behave the same way: no hooks, no
# signing prompt, no background gc while several worktrees commit at once.
REPO_CONFIG = (f"[user]\n\tname = {AUTHOR[0]}\n\temail = {AUTHOR[1]}\n[commit]\n\tgpgsign = false\n[tag]\n\tgpgsign = false\n"
               "[core]\n\thooksPath = /dev/null\n[gc]\n\tauto = 0\n[maintenance]\n\tauto = false\n")
_ENV = {
    "PATH": os.environ.get("PATH") or "/usr/bin:/bin", "HOME": os.environ.get("HOME", str(Path.home())),
    "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": AUTHOR[0], "GIT_AUTHOR_EMAIL": AUTHOR[1], "GIT_COMMITTER_NAME": AUTHOR[0],
    "GIT_COMMITTER_EMAIL": AUTHOR[1],
}


class GitError(RuntimeError):
    pass


async def git(cwd: Path | str, *args: str, ok: tuple[int, ...] | None = (0,), timeout: float = 60.0,
              locks: bool = True) -> tuple[int, str, str]:
    """Run git in *cwd*; raise GitError unless the exit code is in *ok* (None: any). ``locks=False`` is for reads
    in a worktree an agent may be committing in at the same moment (no opportunistic index refresh)."""
    env = dict(_ENV, **({} if locks else {"GIT_OPTIONAL_LOCKS": "0"}))
    cmd = [GIT_BIN, "-C", str(cwd), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
           "-c", "core.quotepath=false", "-c", "gc.auto=0", *args]
    proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, env=env)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        raise
    rc = proc.returncode if proc.returncode is not None else -1
    o, e = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    if ok is not None and rc not in ok:
        raise GitError(f"git {args[0] if args else ''} 失败（{rc}）：{(e or o).strip()[:300]}")
    return rc, o, e


@functools.lru_cache(maxsize=256)
def _glob_re(pattern: str) -> re.Pattern[str]:
    if pattern.endswith("/"):
        pattern += "**"
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def matches(path: str, globs: list[str]) -> bool:
    """``*`` stays inside one directory, ``**`` crosses them, a trailing ``/`` means everything below; a glob that starts
    with ``!`` leaves out what it matches (``["**", "!tests/**"]``: everything but the tests)."""
    if any(g.startswith("!") and _glob_re(g[1:]).match(path) for g in globs):
        return False
    return any(_glob_re(g).match(path) for g in globs if not g.startswith("!"))


def with_requirement(readme: str, requirement: str, title: str | None = None) -> str:
    """README.md with its ``## 需求`` section replaced by *requirement* (appended when there is none), and its
    first ``# `` heading by *title*: the demo's own name must not sit over somebody else's requirement."""
    if title:
        lines = readme.splitlines(keepends=True)
        at = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
        if at is not None:
            lines[at] = f"# {title.strip()}\n"
            readme = "".join(lines)
    lines = readme.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.strip() == "## 需求"), None)
    if start is None:
        return readme.rstrip("\n") + "\n\n## 需求\n\n" + requirement.strip() + "\n"
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    tail = "".join(lines[end:])
    return "".join(lines[: start + 1]) + "\n" + requirement.strip() + "\n" + ("\n" + tail if tail else "")


def _fresh_tree(template: Path, repo: Path, requirement: str, title: str | None = None) -> None:
    if repo.exists():
        shutil.rmtree(repo)  # a half-made repo from an interrupted start
    shutil.copytree(template, repo, ignore=shutil.ignore_patterns(".git", ".DS_Store", "node_modules"))
    readme = repo / "README.md"
    if requirement and readme.exists():
        readme.write_text(with_requirement(readme.read_text(encoding="utf-8"), requirement, title), encoding="utf-8")


async def head(cwd: Path | str) -> str:
    return (await git(cwd, "rev-parse", "HEAD", locks=False))[1].strip()


async def short_head(cwd: Path | str) -> str:
    return (await git(cwd, "rev-parse", "--short", "HEAD", locks=False))[1].strip()


async def merge_base(cwd: Path | str, a: str, b: str) -> str:
    return (await git(cwd, "merge-base", a, b, locks=False))[1].strip()


OVERLAY_PARTS = ("aidlc/official", "aidlc/knowledge", "tests/enterprise")


def _overlay(repo: Path, pack: Path | list[Path] | None) -> None:
    """The spec packs a team works by, into a repo that does not have them yet: each part (the official AI-DLC
    agents, the company's knowledge, its checks) from the first pack that has it."""
    packs = [] if pack is None else [pack] if isinstance(pack, Path) else list(pack)
    for rel in OVERLAY_PARTS:
        dst = repo / rel
        src = next((p / rel for p in packs if (p / rel).is_dir()), None)
        if src is not None and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".DS_Store"))


async def create_repo(template: Path, repo: Path, requirement: str, title: str, existing: bool = False,
                      overlay: Path | list[Path] | None = None, keep_title: bool = False) -> str:
    """The run's repository from the demo template (what ``demo/new_target.sh`` does), or, when *existing*, from a
    copy of an existing project the team takes over (its README title is kept); returns the base commit.
    *keep_title*: a team's starter (a company template with the product's name) keeps its README title too."""
    if (repo / ".git").exists():
        rc, out, _ = await git(repo, "rev-parse", "--verify", "-q", "HEAD", ok=None)
        if rc == 0:
            return out.strip()
    await asyncio.to_thread(_fresh_tree, template, repo, requirement,
                            title if requirement and not existing and not keep_title else None)
    await asyncio.to_thread(_overlay, repo, overlay)
    await git(repo, "init", "-q", "-b", "main")
    with open(repo / ".git" / "config", "a", encoding="utf-8") as fh:
        fh.write(REPO_CONFIG)
    (repo / ".git" / "info").mkdir(exist_ok=True)  # shared by every worktree of the repo
    with open(repo / ".git" / "info" / "exclude", "a", encoding="utf-8") as fh:
        fh.write("\n".join(p + "\n" for p in HOST_PREFIXES))
    await git(repo, "add", "-A")
    await git(repo, "commit", "-q", "-m", f"接手：{title}" if existing else f"需求：{title}")
    return await head(repo)


async def add_worktree(repo: Path, path: Path, branch: str, start: str) -> bool:
    """*branch* (created at *start* if new) checked out at *path*; False when it already was (a restart)."""
    if (path / ".git").exists():
        return False
    if path.exists():
        await asyncio.to_thread(shutil.rmtree, path)  # a leftover folder that is not a worktree
    path.parent.mkdir(parents=True, exist_ok=True)
    rc, _, _ = await git(repo, "worktree", "add", "-q", "-b", branch, str(path), start, ok=None)
    if rc == 0:
        return True
    await git(repo, "worktree", "prune")  # the branch exists already, or a deleted worktree is still registered
    await git(repo, "worktree", "add", "-q", str(path), branch)
    return False


def _count_lines(root: Path, paths: list[str]) -> dict[str, int]:
    out = {}
    for rel in paths[:500]:
        try:
            with open(root / rel, "rb") as fh:
                data = fh.read(2_000_000)
        except OSError:
            out[rel] = 0
            continue
        out[rel] = 0 if b"\0" in data[:8192] else data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return out


def _split0(text: str) -> list[str]:
    return [p for p in text.split("\0") if p]


# KiroCrew writes its own files into every agent's working directory (.kiro/settings/cli.json and a lock, an empty
# .kiro/agents/): they are never a role's work, never committed, never an out-of-area write. A project's own steering
# (.kiro/steering/) is the project's: it is committed and every role's session loads it.
HOST_PREFIXES = (".kiro/settings/", ".kiro/agents/")


def is_host_path(path: str) -> bool:
    return path.startswith(HOST_PREFIXES)


def _raw_numstat(diff: str) -> dict[str, dict[str, Any]]:
    """``git diff --raw --numstat -z`` output → {path: {path, added, removed, status}} (host paths left out)."""
    tokens, status, files = diff.split("\0"), {}, {}
    i = 0
    while i < len(tokens):  # raw records ":<modes> <shas> <letter>" + path first, then "added\tremoved\tpath"
        tok = tokens[i]
        if tok.startswith(":") and i + 1 < len(tokens):
            status[tokens[i + 1]] = tok.split()[-1][:1]
            i += 2
            continue
        parts = tok.split("\t", 2)
        if len(parts) == 3 and not is_host_path(parts[2]):
            a, r, p = parts
            letter = status.get(p, "M")
            files[p] = {"path": p, "added": int(a) if a.isdigit() else 0, "removed": int(r) if r.isdigit() else 0,
                        "status": letter if letter in ("A", "M", "D") else "M"}
        i += 1
    return files


async def diff_files(cwd: Path, base: str, ref: str, limit: int = 400) -> list[dict[str, Any]]:
    """What *ref* has changed since *base*, committed work only (the deliverable): files sorted by path."""
    _, out, _ = await git(cwd, "diff", "--raw", "--numstat", "-z", "--no-renames", base, ref, locks=False)
    return sorted(_raw_numstat(out).values(), key=lambda f: f["path"])[:limit]


async def stats(wt: Path, fork: str) -> dict[str, Any]:
    """What a worktree changed since *fork*, uncommitted and untracked work included: files (biggest first, 12),
    total line counts, every changed path, and its commits (newest last, 8)."""
    (_, diff, _), (_, others, _), (_, log, _) = await asyncio.gather(
        git(wt, "diff", "--raw", "--numstat", "-z", "--no-renames", fork, locks=False),
        git(wt, "ls-files", "--others", "--exclude-standard", "-z", locks=False),
        git(wt, "log", "--format=%h%x1f%s%x1f%ct%x1e", "-n", "8", f"{fork}..HEAD", locks=False))
    files = _raw_numstat(diff)
    untracked = [p for p in _split0(others) if p not in files and not is_host_path(p)]
    counts = await asyncio.to_thread(_count_lines, wt, untracked) if untracked else {}
    for p in untracked:
        files[p] = {"path": p, "added": counts.get(p, 0), "removed": 0, "status": "A"}
    ordered = sorted(files.values(), key=lambda f: (-(f["added"] + f["removed"]), f["path"]))
    commits = []
    for rec in log.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) == 3:
            commits.append({"sha": parts[0], "subject": parts[1][:200], "at": float(parts[2]) if parts[2].isdigit() else 0.0})
    return {"files": ordered[:12], "count": len(ordered), "paths": [f["path"] for f in ordered],
            "lines": {"added": sum(f["added"] for f in ordered), "removed": sum(f["removed"] for f in ordered)},
            "commits": commits[::-1]}


async def committed_paths(wt: Path, fork: str) -> list[str]:
    """Paths the branch's commits changed since *fork*."""
    paths = _split0((await git(wt, "diff", "--name-only", "-z", "--no-renames", fork, "HEAD", locks=False))[1])
    return [p for p in paths if not is_host_path(p)]


async def commit_leftovers(wt: Path, globs: list[str], role: str) -> tuple[list[str], str | None]:
    """Commit what the agent left uncommitted, but only inside its writable globs; (paths, new head) or ([], None)."""
    _, out, _ = await git(wt, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
    mine = [rec[3:] for rec in _split0(out) if len(rec) > 3 and not is_host_path(rec[3:]) and matches(rec[3:], globs)][:500]
    if not mine:
        return [], None
    await git(wt, "add", "-A", "--", *mine)
    rc, _, _ = await git(wt, "commit", "-q", "-m", f"[{role}] （app 代提交）", "--", *mine, ok=None)
    return (mine, await short_head(wt)) if rc == 0 else ([], None)


async def reset_clean(wt: Path) -> None:
    """Back to HEAD exactly (the integration worktree only holds merged work; test runs may leave files)."""
    if (await git(wt, "status", "--porcelain=v1", "-z", "--untracked-files=all"))[1]:
        await git(wt, "reset", "-q", "--hard", "HEAD")
        await git(wt, "clean", "-q", "-fd")


async def fast_forward(wt: Path, ref: str) -> bool:
    """Move the worktree's branch up to *ref* when that is a fast-forward (its own work is already in *ref*)."""
    await reset_clean(wt)
    return (await git(wt, "merge", "--ff-only", "-q", ref, ok=None))[0] == 0


async def merge(run_wt: Path, branch: str, message: str) -> dict[str, Any]:
    """``merge --no-ff`` *branch* into the run branch; a conflict is recorded and aborted. A branch with nothing
    new (or merged already, before a restart) is "Already up to date": no empty merge commit."""
    for attempt in (1, 2):
        rc, out, err = await git(run_wt, "merge", "--no-ff", "--no-edit", "-m", message, branch, ok=None)
        if rc == 0:
            return {"ok": True, "conflicts": [], "note": None}
        conflicts = _split0((await git(run_wt, "diff", "--name-only", "--diff-filter=U", "-z", ok=None))[1])
        await git(run_wt, "merge", "--abort", ok=None)
        if conflicts or attempt == 2:
            break
        await reset_clean(run_wt)  # not a conflict: leftovers in the integration worktree got in the way
    note = "、".join(conflicts[:6]) if conflicts else ((err or out).strip().splitlines() or ["合并失败"])[0][:200]
    return {"ok": False, "conflicts": conflicts, "note": note}
