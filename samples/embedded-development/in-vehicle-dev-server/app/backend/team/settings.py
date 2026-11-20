"""The app's own settings: ``settings.json`` in its data directory, edited on 设置 (the dashboard owner only, as
every route of this app is: handlers.py), checked before it is saved and written atomically.

Without the file the app behaves exactly as the shipped team file says: every default here is read from
``team/team-vstatd.json``, so an install that never opens 设置 runs as before.

  mode            ``direct`` or ``servers``: the team file's ``connectors`` (D17)
  server_configs  each MCP server's ``--config`` file (``build``, ``bench``), as the team file's ``servers`` names it
  baseline        the baseline directory the direct-mode bench uses (the team file's ``bench.baseline``); in servers
                  mode the bench server's own ``baseline`` is read from its configuration and this one is not used
  docker          the direct-mode checks' Docker: ``runner`` an executable that speaks Docker's command line ("": the
                  one found on this machine, constants.DOCKER_BIN), ``host`` a daemon as ``docker -H`` takes it
                  ("": the local one)
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
import tempfile
from pathlib import Path
from typing import Any

MODES = ("direct", "servers")
SERVERS = ("build", "bench")
# mcp/build/config.example.toml: optional, all three or none, for `run_check release`
RELEASE_PATHS = ("bench_results", "bench_runs", "bench_baseline")
DOCKER_SCHEMES = ("unix://", "tcp://", "ssh://", "npipe://", "fd://")
MAX_PATH = 500  # a path longer than this is the page sending something wrong, not a setting
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
    return check(data, team)[0]


def save(path: Path | str, settings: dict[str, Any]) -> None:
    """*settings* into *path*, replaced in one step (a half-written file would be read as none)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _path(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _abs(value: Any, key: str, probs: list[str]) -> str:
    """The path as it was written (``~`` and ``${sample}`` kept: the modules that use it expand them), or "" with
    what is wrong about it in *probs*. Checked on the expanded form, because that is what is opened."""
    p = _path(value)
    if not p:
        probs.append(f"「{FIELD[key]}」不能留空")
    elif len(p) > MAX_PATH:
        probs.append(f"「{FIELD[key]}」太长了（最多 {MAX_PATH} 个字符）")
    elif not os.path.isabs(os.path.expanduser(p)):
        probs.append(f"「{FIELD[key]}」要写绝对路径，或以 ~ 开头")
    else:
        return p
    return ""


def check(data: Any, team: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """(the settings that hold, what is wrong with the rest). Keys this version does not know are dropped, and a
    field that does not hold up keeps *team*'s default: a saved file can never leave the app without settings. A
    field sent back exactly as the team file has it is that default and is not checked again (the team file may
    write ``${sample}/…``, which paths.py fills in later)."""
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
        out["baseline"] = _abs(data["baseline"], "baseline", probs) or out["baseline"]
    docker = data.get("docker")
    if docker is not None and not isinstance(docker, dict):
        probs.append("Docker 的设置格式不对" + AGAIN)
    elif docker:
        if "runner" in docker:
            runner = _path(docker["runner"])
            if len(runner) > MAX_PATH:
                probs.append(f"「{FIELD['runner']}」太长了（最多 {MAX_PATH} 个字符）")
            elif runner and not os.path.isabs(os.path.expanduser(runner)):
                probs.append(f"「{FIELD['runner']}」要写绝对路径（留空用本机找到的 docker）")
            else:
                out["docker"]["runner"] = runner
        if "host" in docker:
            host = _path(docker["host"])
            if len(host) > MAX_PATH:
                probs.append(f"「{FIELD['host']}」太长了（最多 {MAX_PATH} 个字符）")
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

    ``{ok, detail, missing, lines, config}``; ``ok`` None when the configuration could not be read at all. The app
    never writes either file: a person adds the lines in the build server's own file (its user owns it)."""
    conf = str(settings["server_configs"].get("build") or "")
    out: dict[str, Any] = {"ok": None, "detail": "", "missing": [], "lines": [], "config": conf}
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
        state = state.rstrip("/")
        out["lines"] = [f'bench_results = "{state}/results"', f'bench_runs = "{state}/runs"',
                        f'bench_baseline = "{baseline}"']
        out["detail"] = f"缺 {short}，build 服务器判不了 release 检查：把下面三行加到 build.toml 的 [paths] 里"
    else:
        out["detail"] = (f"缺 {short}，build 服务器判不了 release 检查；"
                         + (bench_why or "bench 服务器的配置里没有 paths.state 或 paths.baseline，推不出要填什么"))
    return out
