"""Names and paths shared by every module."""

import glob as _glob
import os as _os
import shutil as _shutil
import subprocess as _subprocess
from pathlib import Path as _Path

APP_NAME = "aidlc-team"
TAG_PREFIX = "[aidlc-team "  # first line of every task this app spawns: [aidlc-team run=… role=… branch=… worktree=…]

# KiroCrew only lets a sub-agent work under ~/workspace(s) or ~/workplace(s) (spawn refuses any other cwd), so every
# run's repository and worktrees live here.
WORK_ROOT = _Path.home() / "workplace" / "aidlc-team"

APP_ROOT = _Path(__file__).resolve().parents[2]  # the app's folder: the installed copy or the dev checkout
TEAM_FILE = APP_ROOT / "team" / "team.json"
TEAM_DIR = APP_ROOT / "team"  # other team files (team-*.json) a run may name
TASK_TEMPLATE_FILE = APP_ROOT / "team" / "task_template.md"
TARGET_TEMPLATE = APP_ROOT / "demo" / "target-template"

TICK_S = 2.0  # every active run is moved forward this often
EVENTS_KEPT = 200  # the board shows the latest events


def _binary(env: str, preferred: tuple[str, ...], name: str) -> str:
    """An executable: ``$env``, else the first of *preferred* that exists, else *name* on PATH or the usual places."""
    if _os.environ.get(env):
        return _os.environ[env]
    for path in preferred:
        if _os.access(path, _os.X_OK):
            return path
    path = _os.pathsep.join([_os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"])
    return _shutil.which(name, path=path) or name


def _node() -> str:
    """The test runner's node: ``$KIROCREW_TEAM_NODE``, else the first candidate that is node 22 or newer (the test
    run passes ``--test-force-exit``, which an older node rejects: every file would read "跑不起来")."""
    if _os.environ.get("KIROCREW_TEAM_NODE"):
        return _os.environ["KIROCREW_TEAM_NODE"]
    nvm = sorted(_glob.glob(_os.path.expanduser("~/.nvm/versions/node/v*/bin/node")),
                 key=lambda p: [int(x) for x in p.split("/v")[-1].split("/")[0].split(".") if x.isdigit()], reverse=True)
    found = [p for p in ("/opt/homebrew/bin/node", _shutil.which("node") or "", "/usr/local/bin/node", *nvm)
             if p and _os.access(p, _os.X_OK)]
    for path in found:
        try:
            out = _subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, _subprocess.SubprocessError):
            continue
        if out.startswith("v") and out[1:].split(".")[0].isdigit() and int(out[1:].split(".")[0]) >= 22:
            return path
    return found[0] if found else "node"


NODE_BIN = _node()
# The real git before macOS's /usr/bin/git, an xcrun shim that costs ~30 ms per call.
GIT_BIN = _binary("KIROCREW_TEAM_GIT", ("/opt/homebrew/bin/git", "/usr/local/bin/git",
                                         "/Library/Developer/CommandLineTools/usr/bin/git",
                                         "/Applications/Xcode.app/Contents/Developer/usr/bin/git"), "git")
