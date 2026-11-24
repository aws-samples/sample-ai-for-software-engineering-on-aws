"""The app's own settings: ``settings.json`` in its data directory, edited on 设置 (the dashboard owner only, as
every route of this app is: handlers.py), checked before it is saved and written atomically.

Without the file the app behaves exactly as the shipped team file says: every default here is read from
``team/team-vstatd.json``, so an install that never opens 设置 runs as before.

  mode            ``direct`` or ``servers``: the team file's ``connectors`` (D17)
  server_configs  each MCP server's ``--config`` file (``build``, ``bench``), as the team file's ``servers`` names it
  baseline        the baseline directory the direct-mode bench uses (the team file's ``bench.baseline``); in servers
                  mode the bench server's own ``baseline`` is read from its configuration and this one is not used.
                  Security-relevant: the folder is bind-mounted ``:ro`` into the container the checks run in
                  (checks.py), so it is kept inside the scenario folder, ``~/workplace/vstatd-team`` or the
                  ``baseline/`` folder of the app's data directory (see :func:`baseline_refused`)
  docker          the direct-mode checks' Docker: ``runner`` an executable that speaks Docker's command line ("": the
                  one found on this machine, constants.DOCKER_BIN), ``host`` a daemon as ``docker -H`` takes it
                  ("": the local one). Security-relevant: the runner is run with every check, and a ``tcp://`` host
                  gets the checks and their mounts over the network unencrypted
  board_decides   who may approve a bench request: with it on, 批准 / 拒绝 are on the board in servers mode too
                  (D17). Security-relevant: it is the dashboard owner's switch, as this whole page is.

The two servers' configuration files belong to the servers, not to the app: it keeps their paths here, reads them,
and never writes them (the build server checks every mounted folder's identity, ``mcp/build/buildserver/core.py``).
:func:`release_inputs` reads the build server's ``[paths]`` for the three ``bench_*`` entries ``run_check release``
needs and says which lines to paste; pasting them is a person's job, in the server's own file.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from . import paths as paths_mod
from .httpkit import AppError

MODES = ("direct", "servers")
SERVERS = ("build", "bench")
# mcp/build/config.example.toml: optional, all three or none, for `run_check release`
RELEASE_PATHS = ("bench_results", "bench_runs", "bench_baseline")
DOCKER_SCHEMES = ("unix://", "tcp://", "ssh://", "npipe://", "fd://")
MAX_PATH = 500  # a path longer than this is the page sending something wrong, not a setting
SAMPLE = "${sample}"  # the scenario folder as the team file writes it; paths.py fills it in after apply()
TEAM_DIR = "~/workplace/vstatd-team"  # the bench owner's own folder (bench.OWN_BASELINE is in it)
DATA_BASELINE = "baseline"  # the one folder of the app's data directory a baseline may be in
# a NUL or a newline is the page sending something wrong: a newline inside a path would be read back as a second
# line of the server's own TOML, and a NUL cannot be opened at all
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
AGAIN = "：刷新页面再存一次"
FIELD = {"build": "build 服务器的配置文件", "bench": "bench 服务器的配置文件", "baseline": "基线目录",
         "runner": "Docker 命令", "host": "Docker 主机"}


def config_of(team: dict[str, Any], which: str) -> str:
    """The ``--config`` file of one server as the team file names it ("" when it names none)."""
    words = (team.get("servers") or {}).get(which)
    if not isinstance(words, list) or not all(isinstance(w, str) for w in words) or "--config" not in words[:-1]:
        return ""
    return words[words.index("--config") + 1]


def defaults(team: dict[str, Any]) -> dict[str, Any]:
    """Today's behaviour, read from *team*: what the app uses when there is no settings file."""
    return {"mode": team.get("connectors") if team.get("connectors") in MODES else "direct",
            "server_configs": {k: config_of(team, k) for k in SERVERS},
            "baseline": str((team.get("bench") or {}).get("baseline") or ""),
            "docker": {"runner": "", "host": ""},
            "board_decides": (team.get("servers") or {}).get("board_decides") is True}


def load(path: Path | str, team: dict[str, Any]) -> dict[str, Any]:
    """The settings in *path*, checked against *team*'s defaults; the defaults alone when there is no file, it
    cannot be read, or what it holds does not hold up (a problem is shown on 设置, it never stops a run)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaults(team)
    return check(data, team, Path(path).parent)[0]


def save(path: Path | str, settings: dict[str, Any]) -> None:
    """*settings* into *path*, replaced in one step (a half-written file would be read as none): on disk before the
    rename, and no temporary file left behind when anything fails."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def _path(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _bad_chars(key: str) -> str:
    return f"「{FIELD[key]}」里有不能用的字符（空字节、换行一类）"


def _home() -> str:
    return os.path.realpath(os.path.expanduser("~"))


def _under(p: str, root: str) -> bool:
    """*p* is below *root* (the root itself is not)."""
    return bool(root) and p.startswith(root.rstrip(os.sep) + os.sep)


def _text(p: str, key: str, probs: list[str]) -> bool:
    """Whether *p* can be a path at all: not empty, not too long, no control character."""
    if not p:
        probs.append(f"「{FIELD[key]}」不能留空")
    elif len(p) > MAX_PATH:
        probs.append(f"「{FIELD[key]}」太长了（最多 {MAX_PATH} 个字符）")
    elif CONTROL.search(p):
        probs.append(_bad_chars(key))
    else:
        return True
    return False


def _abs(value: Any, key: str, probs: list[str]) -> str:
    """The path as it was written (``~`` kept: the modules that use it expand it), or "" with what is wrong about it
    in *probs*. Checked on the expanded form, because that is what is opened."""
    p = _path(value)
    if not _text(p, key, probs):
        return ""
    if not os.path.isabs(os.path.expanduser(p)):
        probs.append(f"「{FIELD[key]}」要写绝对路径，或以 ~ 开头")
        return ""
    return p


def _roots(data_dir: Path | str | None) -> list[str]:
    """Where a baseline may be below, resolved: the bench owner's folder and the scenario folder (when it is known).
    A root is left out when a symbolic link on its way leads it out of where it is written (``~/workplace/vstatd-team``
    as a link to ``~``, to ``~/.ssh`` or to another user's home would let that folder in), or when it is the home
    folder or above it."""
    out = [os.path.abspath(os.path.expanduser(TEAM_DIR))]
    try:
        out.append(os.path.abspath(paths_mod.sample_dir(data_dir)))
    except AppError:  # setup.sh has not run: a ${sample} path is refused below
        pass
    home, real = _home(), [(os.path.realpath(p), p) for p in out]
    return [r for r, p in real if (r == p or _under(r, p)) and r != home and not _under(home, r)]


def _data_baseline(data_dir: Path | str | None) -> str:
    """The one folder of the app's data directory a baseline may be (it or below it), resolved; "" without a data
    directory or when ``baseline/`` is a link out of the data directory. The rest of the data directory (runs/,
    settings.json, sample.json) is the app's own."""
    if not data_dir:
        return ""
    real = os.path.realpath(os.path.join(data_dir, DATA_BASELINE))
    return real if real == os.path.join(os.path.realpath(data_dir), DATA_BASELINE) else ""


def baseline_refused(real: str, data_dir: Path | str | None) -> str:
    """Why the baseline that resolves to *real* may not be mounted into the checks' container ("" when it may): it
    must be below one of :func:`_roots` or be (or be below) the data directory's ``baseline/`` folder, which must
    then be a folder, never the home folder itself, and with no part below its root starting with a dot (``.aws``,
    ``.ssh``). Read when 设置 saves it and again by checks.py right before ``docker run``, on the path it mounts."""
    data = _data_baseline(data_dir)
    in_data = bool(data) and (real == data or _under(real, data))
    root = data if in_data else next((r for r in _roots(data_dir) if _under(real, r)), None)
    if root is None or real == _home():
        return (f"「{FIELD['baseline']}」要在 {SAMPLE}/…、{TEAM_DIR}/… 或 app 数据目录的 {DATA_BASELINE}/ 里"
                "（它会被只读挂进跑检查的容器）")
    if any(part.startswith(".") for part in PurePosixPath(os.path.relpath(real, root)).parts):
        return f"「{FIELD['baseline']}」里不能有以 . 开头的一段（比如 .aws、.ssh）"
    if in_data and not os.path.isdir(real):
        return f"「{FIELD['baseline']}」在 app 的数据目录里时要是一个已有的文件夹"
    return ""


def _baseline(value: Any, probs: list[str], data_dir: Path | str | None) -> str:
    """The baseline as it was written (``~`` and ``${sample}`` kept: paths.py and the checks expand them), or "".

    It is bind-mounted ``:ro`` into the container the checks run in (checks.py docker_command), which runs the
    agents' code with network access, so a text field here decides which folder of this machine that code reads.
    It must resolve (``realpath``, after ``${sample}`` and ``~`` are filled in, so no ``..`` and no symbolic link
    leads out) to where :func:`baseline_refused` allows. The data directory itself sits under ``~/.kiro``, so the dot
    rule is for the part below the root."""
    p = _path(value)
    if not _text(p, "baseline", probs):
        return ""
    if p.startswith(SAMPLE + "/"):
        try:
            full = str(paths_mod.sample_dir(data_dir)) + p[len(SAMPLE):]
        except AppError as exc:
            probs.append(f"「{FIELD['baseline']}」写的是 {SAMPLE}/…，可是{exc}")
            return ""
    elif os.path.isabs(os.path.expanduser(p)):
        full = os.path.expanduser(p)
    else:
        probs.append(f"「{FIELD['baseline']}」要写绝对路径，或以 ~ 或 {SAMPLE}/ 开头")
        return ""
    why = baseline_refused(os.path.realpath(full), data_dir)
    if ".." in PurePosixPath(full).parts:
        probs.append(f"「{FIELD['baseline']}」不能用 .. 跳到别处")
    elif why:
        probs.append(why)
    else:
        return p
    return ""


def _runner(value: Any, probs: list[str]) -> str | None:
    """The Docker command as it was written ("": the one found on this machine), or None with what is wrong in
    *probs*. Security-relevant: it is run with every check, so it must be an executable file."""
    runner = _path(value)
    if not runner:
        return ""
    if not _text(runner, "runner", probs):
        return None
    full = os.path.expanduser(runner)
    if not os.path.isabs(full):
        probs.append(f"「{FIELD['runner']}」要写绝对路径（留空用本机找到的 docker）")
    elif not (os.path.isfile(full) and os.access(full, os.X_OK)):
        probs.append(f"「{FIELD['runner']}」不是一个能执行的文件：{runner}")
    else:
        return runner
    return None


def check(data: Any, team: dict[str, Any], data_dir: Path | str | None = None) -> tuple[dict[str, Any], list[str]]:
    """(the settings that hold, what is wrong with the rest). Keys this version does not know are dropped, and a
    field that does not hold up keeps *team*'s default: a saved file can never leave the app without settings. A
    field sent back exactly as the team file has it is that default and is not checked again (the team file may
    write ``${sample}/…``, which paths.py fills in later). *data_dir*: the app's, where a baseline may be and where
    ``sample.json`` says which the scenario folder is."""
    probs: list[str] = []
    out = defaults(team)
    if not isinstance(data, dict):
        return out, ["设置的格式不对" + AGAIN]
    if "mode" in data:
        if data["mode"] in MODES:
            out["mode"] = data["mode"]
        else:
            probs.append("「模式」只能是 direct 或 servers")
    confs = data.get("server_configs")
    if confs is not None and not isinstance(confs, dict):
        probs.append("服务器配置文件的格式不对" + AGAIN)
    elif confs:
        for k in SERVERS:
            if k in confs and _path(confs[k]) != out["server_configs"][k]:
                out["server_configs"][k] = _abs(confs[k], k, probs) or out["server_configs"][k]
    if "baseline" in data and _path(data["baseline"]) != out["baseline"]:
        out["baseline"] = _baseline(data["baseline"], probs, data_dir) or out["baseline"]
    docker = data.get("docker")
    if docker is not None and not isinstance(docker, dict):
        probs.append("Docker 的设置格式不对" + AGAIN)
    elif docker:
        if "runner" in docker:
            runner = _runner(docker["runner"], probs)
            if runner is not None:
                out["docker"]["runner"] = runner
        if "host" in docker:
            host = _path(docker["host"])
            if len(host) > MAX_PATH:
                probs.append(f"「{FIELD['host']}」太长了（最多 {MAX_PATH} 个字符）")
            elif CONTROL.search(host):
                probs.append(_bad_chars("host"))
            elif host and not host.startswith(DOCKER_SCHEMES):
                probs.append(f"「{FIELD['host']}」要以 {'、'.join(DOCKER_SCHEMES)} 开头（留空用本机的 Docker）")
            else:
                out["docker"]["host"] = host
    if "board_decides" in data:
        if isinstance(data["board_decides"], bool):
            out["board_decides"] = data["board_decides"]
        else:
            probs.append("「谁能批准台架请求」要是 true 或 false")
    if out["mode"] == "servers" and not isinstance(team.get("servers"), dict):
        probs.append("这个团队文件没有 servers，不能切到 servers 模式")
        out["mode"] = "direct"
    return out, probs


def apply(team: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """*team* with what the settings change: the mode, each server's ``--config``, the direct-mode baseline, the
    Docker the direct-mode checks run, and who approves bench requests. The team file on disk is not touched, and
    neither is any server's configuration."""
    out = dict(team)
    out["connectors"] = settings["mode"]
    servers = out.get("servers")
    if isinstance(servers, dict):
        servers = {**servers, "board_decides": settings["board_decides"]}
        for key in SERVERS:
            words, conf = servers.get(key), settings["server_configs"].get(key) or ""
            if conf and isinstance(words, list) and all(isinstance(w, str) for w in words) and "--config" in words[:-1]:
                words = list(words)
                words[words.index("--config") + 1] = conf
                servers[key] = words
        out["servers"] = servers
    if settings["baseline"] and isinstance(out.get("bench"), dict):
        out["bench"] = {**out["bench"], "baseline": settings["baseline"]}
    runner, docker = out.get("check_runner"), settings["docker"]
    if isinstance(runner, dict) and isinstance(runner.get("docker"), list) and runner["docker"]:
        words = list(runner["docker"])
        if docker["runner"]:
            words[0] = os.path.expanduser(docker["runner"])  # nothing downstream expands the docker words
        if docker["host"] and not any(w in ("-H", "--host") for w in words[:-1]):
            words[1:1] = ["-H", docker["host"]]
        out["check_runner"] = {**runner, "docker": words}
    return out


# --- what the servers' own configuration says (read only) ------------------------------------------------------- #

def _toml(path: str) -> tuple[dict[str, Any] | None, str]:
    """A server's configuration file as a dict, or why it could not be read. Only ever read, never written."""
    if not path:
        return None, "还没填这个配置文件的路径"
    try:
        import tomllib  # Python 3.11+ (Kiro Crew's is 3.12); direct mode does not need it
    except ImportError:
        return None, "读服务器的配置要 Python 3.11 以上"
    try:
        return tomllib.loads(Path(path).expanduser().read_text(encoding="utf-8")), ""
    except (OSError, ValueError) as exc:
        return None, f"读不了 {path}：{exc}"


def release_inputs(settings: dict[str, Any]) -> dict[str, Any]:
    """Read only: whether the build server's configuration has the three ``bench_*`` paths its release check needs
    (``mcp/build/config.example.toml``: all three or none), and, when it has not, the lines to paste there, derived
    from the bench server's ``paths.state`` and ``paths.baseline``.

    ``{ok, detail, missing, paste_lines, config}``; ``ok`` None when the configuration could not be read at all.
    The app never writes either file: a person adds the lines in the build server's own file (its user owns it).
    The lines carry the home folder written out, because the build server takes absolute paths only and expands
    no ``~`` (``mcp/build/buildserver/core.py``: "must be absolute"); ``paste_lines`` is the one field a reply
    shows that way (display.py AS_WRITTEN)."""
    conf = str(settings["server_configs"].get("build") or "")
    out: dict[str, Any] = {"ok": None, "detail": "", "missing": [], "paste_lines": [], "config": conf}
    data, why = _toml(conf)
    if data is None:
        out["detail"] = why
        return out
    paths = data.get("paths") if isinstance(data.get("paths"), dict) else {}
    out["missing"] = [k for k in RELEASE_PATHS if not str(paths.get(k) or "").strip()]
    if not out["missing"]:
        out.update(ok=True, detail="、".join(RELEASE_PATHS) + " 三项都有")
        return out
    out["ok"] = False
    bench, bench_why = _toml(str(settings["server_configs"].get("bench") or ""))
    bpaths = bench.get("paths") if isinstance(bench, dict) and isinstance(bench.get("paths"), dict) else {}
    state, baseline = str(bpaths.get("state") or "").strip(), str(bpaths.get("baseline") or "").strip()
    short = "、".join(out["missing"])
    if state and baseline:
        state = os.path.expanduser(state.rstrip("/"))  # the build server expands no ~: write the home folder out
        baseline = os.path.expanduser(baseline)
        out["paste_lines"] = [f'bench_results = "{state}/results"', f'bench_runs = "{state}/runs"',
                              f'bench_baseline = "{baseline}"']
        out["detail"] = f"缺 {short}，build 服务器判不了 release 检查：把下面三行加到 build.toml 的 [paths] 里"
    else:
        out["detail"] = (f"缺 {short}，build 服务器判不了 release 检查；"
                         + (bench_why or "bench 服务器的配置里没有 paths.state 或 paths.baseline，推不出要填什么"))
    return out
