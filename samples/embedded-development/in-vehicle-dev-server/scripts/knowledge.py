"""The knowledge copy the knowledge source indexes (~/workplace/vstatd/knowledge), recorded file by file in
.install-state.json (scripts/state.py, key knowledge_files: path -> sha256), so that neither setup nor cleanup touches a
file it did not write:

- install copies knowledge/ there. A file already there with other content that setup did not write (or wrote, and
  someone changed since) stops it before it changes anything. A file an earlier setup copied and the scenario no
  longer has goes, unless it was changed.
- remove deletes the files setup copied and has not seen changed, then the folders it created once they are empty, and
  says what it kept.

A copy an earlier setup made, before this record (created team_home but no knowledge_files), is taken as setup's
where the scenario has a file of the same path, whatever the file holds now: that setup overwrote those paths on every
run, so a change there is most likely the scenario's own update, and the old cleanup removed the whole folder.

    python3 scripts/knowledge.py plan <knowledge/> <copy>      # what install would do; changes nothing
    python3 scripts/knowledge.py install <knowledge/> <copy>
    python3 scripts/knowledge.py remove <knowledge/> <copy>
"""
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state  # noqa: E402

SKIP_DIRS = {"tools", "__pycache__"}  # knowledge/tools checks the files; it is not knowledge
SKIP_FILES = {".DS_Store"}


def sources(src: Path) -> dict:
    """path relative to *src* -> sha256, for the files the copy holds"""
    out = {}
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if p.is_file() and p.name not in SKIP_FILES and not SKIP_DIRS.intersection(rel.parts[:-1]):
            out[rel.as_posix()] = sha(p)
    return out


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def recorded(src: Path) -> dict:
    data = state.load()
    files = data.get("knowledge_files")
    if isinstance(files, dict):
        return {k: v for k, v in files.items() if isinstance(k, str) and isinstance(v, str)}
    if "team_home" in (data.get("created") or []):  # an earlier setup's copy
        return {rel: "" for rel in sources(src)}
    return {}


def _record(files: dict) -> None:
    data = state.load()
    if files:
        data["knowledge_files"] = files
    else:
        data.pop("knowledge_files", None)
    state.save(data)


def _ours(dst: Path, rel: str, mine: dict) -> bool:
    """the file at *rel* is setup's copy, unchanged since (an earlier setup's copy: any content)"""
    return rel in mine and (mine[rel] == "" or sha(dst / rel) == mine[rel])


def install(src: Path, dst: Path, dry: bool) -> int:
    want, mine = sources(src), recorded(src)
    blocked = [rel for rel, h in want.items()
               if (dst / rel).is_file() and sha(dst / rel) != h and not _ours(dst, rel, mine)]
    blocked += [rel for rel in want if (dst / rel).exists() and not (dst / rel).is_file()]
    if blocked:
        print(f"{dst} has files of its own where setup copies knowledge/ (setup did not write them, or they changed "
              "since): move them away and run setup.sh again. The knowledge copy was not changed.", file=sys.stderr)
        for rel in blocked:
            print(f"  {rel}", file=sys.stderr)
        return 1
    added = sum(1 for rel in want if not (dst / rel).exists())
    updated = sum(1 for rel, h in want.items() if (dst / rel).is_file() and sha(dst / rel) != h)
    gone = [rel for rel in mine if rel not in want and (dst / rel).is_file()]
    kept = [rel for rel in gone if not _ours(dst, rel, mine)]
    if dry:
        print(f"would copy knowledge/ to {dst}: {added} new, {updated} updated, {len(gone) - len(kept)} removed")
        return 0
    if not dst.parent.exists():
        state.main(["add", "created", "team_home"])
    if not dst.exists():
        state.main(["add", "created", "knowledge_dir"])
    files = {}
    for rel, h in want.items():
        target = dst / rel
        if not target.is_file() or sha(target) != h:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / rel, target)
            files[rel] = h
        elif rel in mine:  # setup's copy, unchanged; the same file there before setup stays theirs
            files[rel] = h
    for rel in gone:
        if rel not in kept:
            (dst / rel).unlink()
            _prune((dst / rel).parent, dst)
    files.update({rel: mine[rel] for rel in kept})  # changed since: theirs now, but cleanup still says so
    _record(files)
    print(f"{added} new, {updated} updated, {len(gone) - len(kept)} removed" +
          (f"; kept {len(kept)} changed since setup copied them: {', '.join(kept)}" if kept else ""))
    return 0


def _prune(folder: Path, top: Path) -> None:
    """remove *folder* and its parents up to *top* (excluded) while they are empty"""
    while folder != top and top in folder.parents:
        try:
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent


def remove(src: Path, dst: Path) -> int:
    mine, created = recorded(src), state.load().get("created") or []
    if not mine and not {"team_home", "knowledge_dir"}.intersection(created):
        return 0  # setup copied nothing
    removed, kept = 0, []
    for rel in mine:
        p = dst / rel
        if not p.is_file():
            continue
        if _ours(dst, rel, mine):
            p.unlink()
            _prune(p.parent, dst)
            removed += 1
        else:
            kept.append(rel)
    _record({})
    print(f"- {removed} files of the knowledge copy")
    for folder, key in ((dst, "knowledge_dir"), (dst.parent, "team_home")):
        if key in created or (key == "knowledge_dir" and "team_home" in created):
            try:
                folder.rmdir()
                print(f"- {folder}")
            except FileNotFoundError:
                pass
            except OSError:
                print(f"! kept {folder}: it holds files setup did not copy there")
    for rel in kept:
        print(f"! kept {dst / rel}: changed since setup copied it")
    return 0


def main(argv: list) -> int:
    if len(argv) != 3 or argv[0] not in ("plan", "install", "remove"):
        print("usage: knowledge.py plan|install|remove <knowledge/> <copy>", file=sys.stderr)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    return remove(src, dst) if argv[0] == "remove" else install(src, dst, dry=argv[0] == "plan")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
