"""What setup.sh created, so that cleanup.sh removes only that: a JSON file of lists in the sample folder.

    python3 scripts/state.py add <key> <value>   # record that setup created <value> (a member, a template, ...)
    python3 scripts/state.py has <key> <value>   # exit 0 when it is recorded
    python3 scripts/state.py list <key>          # one value per line
"""
import json
import os
import sys
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / ".install-state.json"


def load() -> dict:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def main(argv: list) -> int:
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
    if cmd == "list":
        print("\n".join(values))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
