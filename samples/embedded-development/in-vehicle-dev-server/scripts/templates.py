"""The team's Kiro agent templates in ~/.kiro/agents/, recorded in .install-state.json (scripts/state.py), as the
agent-team sample's install-example.sh does it: a template that exists with other content, and that setup did not write
itself, is backed up once before it is replaced; cleanup removes the templates setup added and puts the backed-up ones
back.

    python3 scripts/templates.py plan <built dir> <agents dir> <backup dir>      # what install would do; changes nothing
    python3 scripts/templates.py install <built dir> <agents dir> <backup dir>
    python3 scripts/templates.py remove <agents dir> <backup dir>
"""
import filecmp
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state  # noqa: E402


def _recorded(key: str, value: str) -> bool:
    return state.main(["has", key, value]) == 0


def _add(key: str, value: str) -> None:
    state.main(["add", key, value])


def install(built: Path, agents: Path, backup: Path, dry: bool = False) -> list:
    """One line per template: what was (or, *dry*, would be) done."""
    out = []
    if not dry:
        agents.mkdir(parents=True, exist_ok=True)
    # a template an earlier setup wrote under a name the team no longer uses goes (it stays in the record, which
    # cleanup reads with every file optional); one setup backed up, and so did not write first, stays
    names = {f.stem for f in built.glob("*.json")}
    for name in _listed("templates"):
        if name not in names and name not in _listed("backed_up") and (agents / f"{name}.json").exists():
            out.append(f"- {name} (no longer used by the team)")
            if not dry:
                for p in (agents / f"{name}.json", agents / f"{name}.lock"):
                    p.unlink(missing_ok=True)
    for f in sorted(built.glob("*.json")):
        name, dst = f.stem, agents / f.name
        if not dst.exists():
            out.append(f"+ {name}")
            if not dry:
                _add("templates", name)
        elif filecmp.cmp(f, dst, shallow=False):
            out.append(f"= {name} (unchanged)")
            continue
        elif not _recorded("templates", name) and not (backup / f.name).exists():
            out.append(f"~ {name}: exists with other content, backed up to {backup}/ and replaced")
            if not dry:
                backup.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup / f.name)
                _add("backed_up", name)
        else:
            out.append(f"~ {name} (updated)")
        if not dry:
            shutil.copyfile(f, dst)
    return out


def _listed(key: str) -> list:
    return [v for v in state.load().get(key) or [] if isinstance(v, str) and v]


def remove(agents: Path, backup: Path) -> list:
    out = []
    for name in _listed("templates"):
        for p in (agents / f"{name}.json", agents / f"{name}.lock"):
            p.unlink(missing_ok=True)
        out.append(f"- {name}")
    for name in _listed("backed_up"):
        if (backup / f"{name}.json").is_file():
            shutil.move(str(backup / f"{name}.json"), str(agents / f"{name}.json"))
            out.append(f"< {name} (put back)")
    if backup.is_dir() and not any(backup.iterdir()):
        backup.rmdir()
    return out


def main(argv: list) -> int:
    if len(argv) == 4 and argv[0] in ("plan", "install"):
        lines = install(Path(argv[1]), Path(argv[2]), Path(argv[3]), dry=argv[0] == "plan")
    elif len(argv) == 3 and argv[0] == "remove":
        lines = remove(Path(argv[1]), Path(argv[2]))
    else:
        print("usage: templates.py plan|install <built dir> <agents dir> <backup dir>, or remove <agents dir> <backup dir>",
              file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
