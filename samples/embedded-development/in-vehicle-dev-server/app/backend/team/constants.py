"""Names and paths shared by every module."""

import os as _os
import shutil as _shutil
from pathlib import Path as _Path

APP_NAME = "vstatd-team"
TAG_PREFIX = "[vstatd-team "  # first line of every task this app spawns: [vstatd-team run=… role=… branch=… worktree=…]

# KiroCrew only lets a sub-agent work under ~/workspace(s) or ~/workplace(s) (spawn refuses any other cwd), so every
# run's repository and worktrees live here.
WORK_ROOT = _Path.home() / "workplace" / "vstatd-team"

APP_ROOT = _Path(__file__).resolve().parents[2]  # the app's folder: the installed copy or the dev checkout
TEAM_FILE = APP_ROOT / "team" / "team-vstatd.json"  # the team a run gets; other team files (team-*.json) sit beside it

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


# The real git before macOS's /usr/bin/git, an xcrun shim that costs ~30 ms per call.
GIT_BIN = _binary("KIROCREW_TEAM_GIT", ("/opt/homebrew/bin/git", "/usr/local/bin/git",
                                         "/Library/Developer/CommandLineTools/usr/bin/git",
                                         "/Applications/Xcode.app/Contents/Developer/usr/bin/git"), "git")
DOCKER_BIN = _binary("KIROCREW_TEAM_DOCKER", ("/usr/local/bin/docker", "/opt/homebrew/bin/docker",
                                               "/Applications/Docker.app/Contents/Resources/bin/docker"), "docker")
