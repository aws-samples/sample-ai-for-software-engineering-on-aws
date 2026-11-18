"""What setup.sh created, so that cleanup.sh removes only that: a JSON file of lists in this folder (the agent-team
sample's scripts/state.py; $VSTATD_INSTALL_STATE replaces the file, for tests).

    python3 scripts/state.py add <key> <value>      # record that setup created <value> (a member, a template, ...)
    python3 scripts/state.py has <key> <value>      # exit 0 when it is recorded
    python3 scripts/state.py list <key>             # one value per line
    python3 scripts/state.py remove <key> [<value>] # cleanup removed it: forget <value>, or the whole <key>
    python3 scripts/state.py empty                  # exit 0 when nothing is recorded
"""
import json
import os
import sys
from pathlib import Path

STATE = Path(os.environ.get("VSTATD_INSTALL_STATE") or Path(__file__).resolve().parent.parent / ".install-state.json")


def load() -> dict:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, STATE)


def main(argv: list) -> int:
    cmd = argv[0] if argv else ""
    if not ((cmd in ("add", "has") and len(argv) == 3) or (cmd == "list" and len(argv) == 2)
            or (cmd == "remove" and len(argv) in (2, 3)) or (cmd == "empty" and len(argv) == 1)):
        print("usage: state.py add|has <key> <value>, list <key>, remove <key> [<value>], or empty", file=sys.stderr)
        return 2
    data = load()
    if cmd == "empty":
        return 0 if not any(data.values()) else 1
    key = argv[1]
    values = data.get(key) if isinstance(data.get(key), list) else []
    if cmd == "add":
        if argv[2] not in values:
            data[key] = values + [argv[2]]
            save(data)
        return 0
    if cmd == "remove":
        if key in data:
            rest = [v for v in values if v != argv[2]] if len(argv) == 3 else []
            if rest:
                data[key] = rest
            else:
                del data[key]
            save(data)
        return 0
    if cmd == "has":
        return 0 if argv[2] in values else 1
    print("\n".join(values))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
