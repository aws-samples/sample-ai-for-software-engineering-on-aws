"""What setup.sh created, so that cleanup.sh removes only that: a JSON file of lists in this folder (the agent-team
sample's scripts/state.py; $VSTATD_INSTALL_STATE replaces the file, for tests).

    python3 scripts/state.py add <key> <value>   # record that setup created <value> (a member, a template, ...)
    python3 scripts/state.py has <key> <value>   # exit 0 when it is recorded
    python3 scripts/state.py list <key>          # one value per line
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


def main(argv: list) -> int:
    if len(argv) < 2 or argv[0] not in ("add", "has", "list") or (argv[0] != "list" and len(argv) < 3):
        print("usage: state.py add|has <key> <value>, or state.py list <key>", file=sys.stderr)
        return 2
    cmd, key = argv[0], argv[1]
    data = load()
    values = data.get(key) if isinstance(data.get(key), list) else []
    if cmd == "add":
        if argv[2] not in values:
            data[key] = values + [argv[2]]
            tmp = STATE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, STATE)
        return 0
    if cmd == "has":
        return 0 if argv[2] in values else 1
    print("\n".join(values))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
