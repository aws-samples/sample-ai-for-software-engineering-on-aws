# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""BenchService: every guardrail of the `bench` MCP server (README.md).

The physical gate, the approval at the operator console and the action record are the bench's own: physical calls go
through `bench/cc1.sh`, which waits for a person's decision for the build's digest. This service adds the role, the
lease, the build that may be deployed (the one the `build` server judged PASS), the audit log, and the after-bench
checks in a container, with their results published only when they are this run's.
"""

import atexit
import contextlib
import datetime
import fcntl
import grp
import hashlib
import itertools
import json
import os
import pathlib
import pwd
import re
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
import tomllib

READ_ONLY, CONTROLLED_WRITE, PHYSICAL = "read-only", "controlled-write", "physical"
CLASSES = (READ_ONLY, CONTROLLED_WRITE, PHYSICAL)
# The after-bench checks, and whether each reads the approved triage.
CHECKS = {"runtime-limits": False, "logdiff": True}
TOOLS = {
    "bench_status": (READ_ONLY, ()),
    "read_actions": (READ_ONLY, ()),
    "read_result": (READ_ONLY, ("check",)),
    "lease_acquire": (CONTROLLED_WRITE, ()),
    "lease_release": (CONTROLLED_WRITE, ()),
    "run_check": (CONTROLLED_WRITE, ("check",)),
    "request_deploy": (PHYSICAL, ()),
    "request_restart": (PHYSICAL, ()),
    "request_replay": (PHYSICAL, ()),
}
NEEDS_LEASE = {"run_check", "request_deploy", "request_restart", "request_replay"}
VERDICTS = {0: "PASS", 1: "FAIL", 2: "USAGE", 3: "BLOCKED"}
TAIL_BYTES = 8192
ACTIONS_SHOWN = 30
DOCKER_CLIENT_ENV = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH",
                     "DOCKER_TLS_VERIFY", "XDG_RUNTIME_DIR")
RUN_NAME = re.compile(r"run-(\d{1,6})")


class Refused(Exception):
    """The call is not allowed, or the bench refused it; nothing more was done."""


class ConfigError(Exception):
    """The server configuration is unsafe or incomplete; the server does not start."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_nofollow(path, limit=16 * 1024 * 1024, start=None):
    """Bytes of a regular file, or None. Never follows a symlink at the last step and never blocks on a FIFO."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        if start == "tail":
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - limit))
            return (b"[... truncated ...]\n" if size > limit else b"") + f.read(limit)
        return f.read(limit)


def tail(path, limit=TAIL_BYTES):
    data = read_nofollow(path, limit, start="tail")
    return data.decode(errors="replace") if data else ""


def read_json(path):
    try:
        data = json.loads(read_nofollow(path) or b"")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def sha256(path):
    blob = read_nofollow(path, limit=256 * 1024 * 1024)
    return hashlib.sha256(blob).hexdigest() if blob is not None else None


def real_dir(path):
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def inside(path, root):
    path, root = pathlib.Path(path).resolve(), pathlib.Path(root).resolve()
    return path == root or root in path.parents


def write_atomic(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    with os.fdopen(fd, "wb") as f:
        f.write(data.encode() if isinstance(data, str) else data)
    os.replace(tmp, path)


def clear(path):
    if os.path.lexists(path) and not real_dir(path):
        os.unlink(path)
    if real_dir(path):
        for root, dirs, _ in os.walk(path):
            for d in dirs:
                p = os.path.join(root, d)
                if real_dir(p):
                    os.chmod(p, 0o700)
        shutil.rmtree(path)


def private_group(gid):
    """The server user's own group, with no other members."""
    if gid != os.getgid():
        return False
    try:
        members = set(grp.getgrgid(gid).gr_mem)
        me = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return False
    members |= {u.pw_name for u in pwd.getpwall() if u.pw_gid == gid}
    return members <= {me}


def check_trusted(path, name):
    """Refuses a path that someone other than root or the server's user could replace: every folder from the root
    down must be theirs and not writable by others (a sticky folder may hold one of theirs)."""
    path = pathlib.Path(path).resolve()
    chain = [d for d in [*reversed(path.parents), path] if os.path.lexists(d)]
    trusted = (0, os.getuid())
    for i, d in enumerate(chain):
        st = os.lstat(d)
        if st.st_uid not in trusted:
            raise ConfigError(f"paths.{name}: {d} belongs to uid {st.st_uid}, not root or the server's user")
        if st.st_mode & stat.S_IWOTH or (st.st_mode & stat.S_IWGRP and not private_group(st.st_gid)):
            nxt = chain[i + 1] if i + 1 < len(chain) else None
            if not (st.st_mode & stat.S_ISVTX and nxt is not None and os.lstat(nxt).st_uid in trusted):
                raise ConfigError(f"paths.{name}: {d} is writable by other users, who could replace {path}")


class Sandbox:
    """Runs an after-bench check in a container started for that one call: no network, read-only root, no
    capabilities, no new privileges, a fresh home, at most 256 processes and only the given mounts, at their host
    paths. `runner = "none"` runs the command directly, for the server's own tests only."""

    def __init__(self, cfg, env_path, label):
        self.runner = cfg.get("runner", "docker")
        self.image = str(cfg.get("image", "vstatd-build"))
        self.user = str(cfg.get("user", f"{os.getuid()}:{os.getgid()}"))
        if self.user.split(":")[0] in ("0", "root"):
            raise ConfigError("sandbox.user must not be root")
        self.limits = [f"--{k}={cfg[k]}" for k in ("memory", "cpus") if k in cfg]
        self.docker_host = cfg.get("docker_host")
        self.env_path = env_path
        self.label = f"benchserver.state={label}"
        self.names = itertools.count()
        if self.runner == "none" and os.environ.get("BENCHSERVER_UNSANDBOXED_FOR_TESTS") != "1":
            raise ConfigError('sandbox.runner = "none" runs checks without isolation; it is for the server\'s own '
                              "tests only (set BENCHSERVER_UNSANDBOXED_FOR_TESTS=1 there)")
        if self.runner not in ("docker", "none"):
            raise ConfigError(f"sandbox.runner must be docker (or none for tests), not {self.runner!r}")

    def env(self):
        return {"PATH": self.env_path, "HOME": "/tmp/home", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1"}

    def client_env(self):
        env = {k: os.environ[k] for k in DOCKER_CLIENT_ENV if k in os.environ}
        env.setdefault("PATH", "/usr/bin:/bin")
        if self.docker_host:
            env["DOCKER_HOST"] = str(self.docker_host)
        return env

    def argv(self, cmd, name, ro=(), rw=()):
        full = ["docker", "run", "--rm", "--init", "--name", name, "--label", self.label, "--network", "none",
                "--read-only", "--tmpfs", "/tmp:rw,size=256m", "--user", self.user, "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--pids-limit", "256", *self.limits]
        for k, v in self.env().items():
            full += ["-e", f"{k}={v}"]
        for mounts, flag in ((ro, ",readonly"), (rw, "")):
            for p in mounts:
                src = str(p)
                if any(c in src for c in ",\n=") or not pathlib.Path(src).exists():
                    raise RuntimeError(f"cannot mount {src}: missing, or a comma, '=' or newline in its path")
                full += ["--mount", f"type=bind,source={src},target={src}{flag}"]
        return full + [self.image, "sh", "-c", 'mkdir -p "$HOME" && exec "$@"', "sandbox", *map(str, cmd)]

    def reap(self):
        if self.runner != "docker":
            return
        ps = subprocess.run(["docker", "ps", "-aq", "--filter", f"label={self.label}"], capture_output=True,
                            text=True, env=self.client_env(), timeout=60)
        if ps.returncode == 0 and ps.stdout.split():
            subprocess.run(["docker", "rm", "-f", *ps.stdout.split()], capture_output=True, env=self.client_env(),
                           timeout=60)

    def run(self, cmd, log, timeout, ro=(), rw=()):
        name = f"benchserver-{os.getpid()}-{next(self.names)}"
        home = None
        if self.runner == "docker":
            full, run_env = self.argv(cmd, name, ro, rw), self.client_env()
        else:
            home = tempfile.mkdtemp(prefix="benchserver-home-")
            full, run_env = list(map(str, cmd)), {**self.env(), "HOME": home}
        return run_logged(full, run_env, log, timeout, header=cmd,
                          kill=(["docker", "kill", name], run_env) if self.runner == "docker" else None,
                          cleanup=home)


# The process groups this server started that are still running (cc1.sh, a check's container client): stopped when the
# session ends, so that no action goes on, or waits for an approval, with nobody to record its outcome.
RUNNING = set()
RUNNING_LOCK = threading.Lock()


def stop_running():
    """Sends SIGTERM to every process group in RUNNING; returns how many. Does not wait: cc1.sh's own exit handler
    marks an approved action in progress as failed (the target becomes unknown until a person reconciles it)."""
    with RUNNING_LOCK:
        pids = list(RUNNING)
    for pid in pids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGTERM)
    return len(pids)


def alive(holder):
    """Whether the process named in a lease holder (``role:pid:token``) is still running on this host."""
    try:
        pid = int(str(holder).split(":")[1])
    except (IndexError, ValueError):
        return True  # not a holder this server wrote: left to expire
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_logged(argv, env, log, timeout, header=None, kill=None, cleanup=None):
    """Runs argv with its output in `log`; a timeout kills it (and `kill`), nothing is retried."""
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(f"$ {shlex.join(map(str, header or argv))}\n")
            f.flush()
            try:
                proc = subprocess.Popen(list(map(str, argv)), env=env, stdout=f, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, start_new_session=True)
            except FileNotFoundError as e:
                f.write(f"{e}\n")
                return {"outcome": "error", "exit_status": 127}
            with RUNNING_LOCK:
                RUNNING.add(proc.pid)
            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if kill:
                    subprocess.run(kill[0], capture_output=True, env=kill[1], timeout=60)
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, 15)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=20)
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, 9)
                proc.wait()
                f.write(f"\n[stopped after {timeout} s; not retried]\n")
                return {"outcome": "timeout", "exit_status": None}
            finally:
                with RUNNING_LOCK:
                    RUNNING.discard(proc.pid)
        return {"outcome": "ok" if rc == 0 else "failed", "exit_status": rc}
    finally:
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)


class BenchService:
    def __init__(self, config_path, role):
        config_path = pathlib.Path(config_path).resolve()
        cfg = tomllib.loads(config_path.read_text())
        names = ("bench", "checks", "state", "bench_state", "build_results", "baseline", "triage")
        try:
            p = cfg["paths"]
            relative = [k for k in names if not pathlib.Path(str(p[k])).is_absolute()]
            if relative:
                raise ConfigError(f"paths {relative} must be absolute")
            for k in names:
                setattr(self, k, pathlib.Path(p[k]).resolve())
        except KeyError as e:
            raise ConfigError(f"missing paths.{e.args[0]} in {config_path}") from None
        self.cc1_script = self.bench / "cc1.sh"
        if not self.cc1_script.is_file():
            raise ConfigError(f"paths.bench: no cc1.sh in {self.bench}")
        if not (self.checks / "runtime-limits.sh").is_file():
            raise ConfigError(f"paths.checks: no runtime-limits.sh in {self.checks}")
        self.sample = self.bench.parent
        if self.checks.parent != self.sample:
            raise ConfigError("paths.bench and paths.checks must be folders of the same sample")
        for name in ("state", "bench_state"):
            if inside(getattr(self, name), self.sample):
                raise ConfigError(f"paths.{name} must lie outside the sample, which the checks can read")
        if inside(self.state, self.bench_state) or inside(self.bench_state, self.state):
            raise ConfigError("paths.state and paths.bench_state must not contain each other")
        for name in ("build_results", "baseline"):
            if not real_dir(getattr(self, name)):
                raise ConfigError(f"paths.{name}: {getattr(self, name)} is not a folder")
        if not self.triage.parent.is_dir():
            raise ConfigError(f"the folder of paths.triage, {self.triage.parent}, does not exist")
        self.state.mkdir(parents=True, exist_ok=True)
        self.bench_state.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name, path in (("state", self.state), ("bench_state", self.bench_state), ("bench", self.sample),
                           ("build_results", self.build_results), ("baseline", self.baseline),
                           ("triage", self.triage.parent), ("config", config_path)):
            check_trusted(path, name)
        check_trusted(pathlib.Path(__file__).resolve().parent, "the server's own code")
        for d in ("builds", "runs", "results", "logs"):
            (self.state / d).mkdir(exist_ok=True)
        self.audit_log = self.state / "audit.jsonl"
        self.lease_file = self.state / "lease.json"
        self.role = role
        granted = cfg.get("roles", {}).get(role, {}).get("classes", [])
        unknown = [c for c in granted if c not in CLASSES]
        if unknown:
            raise ConfigError(f"role {role}: unknown permission classes {unknown}")
        self.granted = set(granted)
        lease = cfg.get("lease", {})
        self.lease_ttl = int(lease.get("ttl_s", 1800))
        self.timeouts = {"read": 120, "approval": 300, "deploy": 600, "restart": 300, "replay": 900, "check": 600,
                         **cfg.get("timeouts", {})}
        env_path = cfg.get("environment", {}).get("path", "/usr/local/bin:/usr/bin:/bin")
        label = hashlib.sha256(str(self.state).encode()).hexdigest()[:16]
        self.sandbox = Sandbox(cfg.get("sandbox", {}), env_path, label)
        self.holder = f"{role}:{os.getpid()}:{secrets.token_hex(8)}"  # this session's lease identity
        self.current = None  # the call in progress, for the audit if the session ends during it
        self.lock = threading.Lock()
        self.lock_path = self.state / "lock"

    @contextlib.contextmanager
    def exclusive(self):
        with self.lock:
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o640)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)

    # ------------------------------------------------------------------------------------------ audit and calls

    def audit(self, entry):
        line = json.dumps({"t": now(), "role": self.role, "session": self.holder, **entry}, ensure_ascii=False,
                          sort_keys=True, default=repr)
        fd = os.open(self.audit_log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o640)
        try:
            os.write(fd, (line + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def malformed(tool, args):
        """Why a call is not well formed, or None; decided without the lock."""
        cls, params = TOOLS.get(tool, (None, ())) if isinstance(tool, str) else (None, ())
        if cls is None:
            return "unknown tool"
        extra = sorted(set(args) - set(params))
        missing = [p for p in params if p not in args]
        wrong = sorted(k for k, v in args.items() if not isinstance(v, str))
        return (f"unexpected arguments {extra}" if extra else f"missing arguments {missing}" if missing else
                f"arguments that are not strings {wrong}" if wrong else None)

    def call(self, tool, **args):
        """One tool call through the guardrails, audited before and after. Raises Refused, or RuntimeError on an
        unexpected failure (also audited)."""
        cls = TOOLS.get(tool, (None,))[0] if isinstance(tool, str) else None
        entry = {"tool": tool if isinstance(tool, str) else repr(tool), "class": cls, "args": args}
        why = self.malformed(tool, args) or (None if cls in self.granted else
                                             f"role {self.role!r} is not granted {cls}")
        if why:
            self.audit({**entry, "outcome": "refused", "detail": why})
            raise Refused(why if why != "unknown tool" else f"unknown tool {entry['tool']}")
        with self.exclusive():
            started = time.monotonic()
            self.audit({**entry, "outcome": "started"})
            self.current = entry
            try:
                if tool in NEEDS_LEASE:
                    self.need_lease()
                self.sandbox.reap()
                result = getattr(self, "_" + tool)(**args)
            except Refused as e:
                self.audit({**entry, "outcome": "refused", "detail": str(e)})
                raise
            except Exception as e:  # noqa: BLE001 - audited, then reported without internals
                self.audit({**entry, "outcome": "error", "detail": f"{type(e).__name__}: {e}"})
                raise RuntimeError(f"{tool} failed on the server; see the audit log") from e
            finally:
                self.current = None
            self.audit({**entry, "outcome": result.get("outcome", "ok"), "exit_status": result.get("exit_status"),
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        **{k: result[k] for k in ("verdict", "digest", "request") if result.get(k)}})
            return result

    @staticmethod
    def pick(name, value, allowed):
        if not isinstance(value, str) or value not in allowed:
            raise Refused(f"{name} must be one of {', '.join(allowed)}")
        return value

    # ------------------------------------------------------------------------------------------ the bench

    def cc1_env(self):
        env = {k: os.environ[k] for k in DOCKER_CLIENT_ENV if k in os.environ}
        env.update({"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                    "HOME": os.environ.get("HOME", str(self.state)), "LANG": "C.UTF-8",
                    "CC1_BENCH_STATE": str(self.bench_state),
                    "CC1_APPROVAL_TIMEOUT_S": str(int(self.timeouts["approval"])),
                    "CC1_REQUESTER": f"bench MCP server (role {self.role})"})
        if self.sandbox.docker_host:
            env["DOCKER_HOST"] = str(self.sandbox.docker_host)
        return env

    def cc1(self, args, timeout, log_name):
        log = self.state / "logs" / f"{log_name}.log"
        r = run_logged(["bash", self.cc1_script, *args], self.cc1_env(), log, timeout)
        return {**r, "log": log}

    def cc1_read(self, what):
        r = self.cc1([what], self.timeouts["read"], f"read-{what}")
        out = (read_nofollow(r["log"]) or b"").decode(errors="replace").splitlines()[1:]
        for line in reversed(out):
            with contextlib.suppress(ValueError):
                data = json.loads(line)
                if isinstance(data, dict):
                    return data
        return {"error": "\n".join(out)[-500:] or f"cc1.sh {what} exited with {r['exit_status']}"}

    def bench_records(self, n=ACTIONS_SHOWN):
        lines = tail(self.bench_state / "actions.jsonl", 256 * 1024).splitlines()
        out = []
        for line in lines[-n:]:
            with contextlib.suppress(ValueError):
                out.append(json.loads(line))
        return out

    def pending_requests(self):
        out = []
        for p in sorted((self.bench_state / "requests").glob("*.json")) if real_dir(self.bench_state / "requests") else []:
            req = read_json(p)
            if req and not os.path.lexists(self.bench_state / "decisions" / p.name):
                out.append({k: req.get(k) for k in ("id", "action", "digest", "detail", "requested_at",
                                                     "requested_by", "timeout_s")} |
                           {"expired": time.time() >= float(req.get("expires") or 0)})
        return out

    def last_run(self):
        runs = sorted((int(m.group(1)), d) for d in (self.state / "runs").iterdir()
                      if (m := RUN_NAME.fullmatch(d.name)) and real_dir(d) and (d / "run-result.json").is_file())
        return runs[-1][1] if runs else None

    # ------------------------------------------------------------------------------------------ lease

    def lease(self):
        """The lease in force: not expired, and its holder's process still running (a session that died without
        releasing it does not keep the target until the lease lapses)."""
        data = read_json(self.lease_file)
        if not data or float(data.get("expires", 0)) <= time.time() or not alive(data.get("holder")):
            return None
        return data

    def need_lease(self):
        held = self.lease()
        if not held or held.get("holder") != self.holder:
            raise Refused("this session does not hold the lease; call lease_acquire first" if not held else
                          f"the target is leased to another session ({held.get('role')}) until {held.get('until')}")
        self.write_lease()  # each call that needs the lease renews it

    def write_lease(self):
        expires = time.time() + self.lease_ttl
        write_atomic(self.lease_file, json.dumps({
            "holder": self.holder, "role": self.role, "since": (self.lease() or {}).get("since") or now(),
            "expires": expires, "until": datetime.datetime.fromtimestamp(expires, datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")}) + "\n")

    def _lease_acquire(self):
        held = self.lease()
        if held and held.get("holder") != self.holder:
            raise Refused(f"the target is leased to another session ({held.get('role')}) until {held.get('until')}")
        self.write_lease()
        return {"lease": {k: v for k, v in self.lease().items() if k != "holder"}, "yours": True}

    def _lease_release(self):
        held = self.lease()
        if not held:
            return {"released": False, "detail": "no lease was held"}
        if held.get("holder") != self.holder:
            raise Refused("the lease belongs to another session")
        os.unlink(self.lease_file)
        return {"released": True}

    def end_session(self, why="the session ended"):
        """When the server ends (its client went away, a signal): stops what it started that is still running,
        audits the call in progress, and gives the lease back. Takes neither lock, since the call in progress may
        hold them; the lease file is this session's, so removing it races with nobody."""
        with contextlib.suppress(Exception):
            current, stopped = self.current, stop_running()
            if current:
                self.audit({**current, "outcome": "error",
                            "detail": f"{why} during the call; stopped {stopped} process(es) it had started"})
            held = read_json(self.lease_file)
            if held and held.get("holder") == self.holder:
                os.unlink(self.lease_file)
                self.audit({"tool": "lease_release", "class": CONTROLLED_WRITE, "args": {}, "outcome": "ok",
                            "detail": f"released: {why}"})

    # ------------------------------------------------------------------------------------------ reads

    def _bench_status(self):
        held = self.lease()
        run = self.last_run()
        return {"target": self.cc1_read("target"), "supply": self.cc1_read("supply"), "probe": self.cc1_read("probe"),
                "lease": ({k: v for k, v in held.items() if k != "holder"} | {"yours": held["holder"] == self.holder}
                          if held else None),
                "pending_requests": self.pending_requests(),
                "last_run": {"run": run.name, **{k: v for k, v in (read_json(run / "run-result.json") or {}).items()
                                                if k in ("replay_id", "replay_finished", "vm_hwm_kib",
                                                         "approved_digest", "readback_digest")}} if run else None}

    def _read_actions(self):
        return {"actions": self.bench_records()}

    def _read_result(self, check):
        self.pick("check", check, CHECKS)
        return {"check": check, "result": read_json(self.state / "results" / f"{check}.json"),
                "log_tail": tail(self.state / "results" / f"{check}.log")}

    # ------------------------------------------------------------------------------------------ physical actions

    def physical(self, action, args, timeout):
        seen = len(self.bench_records(10 ** 6))
        r = self.cc1(args, timeout + self.timeouts["approval"], action)
        text = (read_nofollow(r["log"]) or b"").decode(errors="replace")
        rid = next((e.get("id") for e in self.bench_records(10 ** 6)[seen:]  # this call's request, not an older one
                    if e.get("event") == "request" and e.get("action") == action), None)
        out = {**{k: v for k, v in r.items() if k != "log"}, "action": action, "request": rid,
               "log_tail": tail(r["log"], 2048)}
        if r["outcome"] == "ok":
            return out
        refused = [ln for ln in text.splitlines() if ln.startswith("refused")]
        if refused:
            raise Refused(f"{refused[-1]} (not retried)")
        if r["outcome"] == "timeout":
            raise Refused(f"{action} did not finish within its timeout; the bench marks the target unknown until a "
                          "person reconciles it at the operator console (not retried)")
        return {**out, "outcome": "failed"}

    def judged_build(self):
        """The build the `build` server's checks/build.sh judged PASS: (path, digest), else Refused."""
        res = read_json(self.build_results / "build.json")
        if not res:
            raise Refused("the build server has published no result of checks/build.sh")
        if res.get("verdict") != "PASS" or res.get("local"):
            raise Refused(f"the published build result is {res.get('verdict')!r}" +
                          (" with --local" if res.get("local") else "") + "; only a PASS build is deployed")
        digest = (res.get("details") or {}).get("digest")
        artifact = self.build_results / "artifacts" / "vstatd"
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise Refused("the published build result records no digest")
        blob = read_nofollow(artifact, limit=64 * 1024 * 1024)
        if blob is None or hashlib.sha256(blob).hexdigest() != digest:
            raise Refused("the published artifact is not the build the check judged (its SHA-256 differs)")
        copy = self.state / "builds" / digest
        if sha256(copy) != digest:
            write_atomic(copy, blob)
        return copy, digest, res.get("commit")

    def _request_deploy(self):
        copy, digest, commit = self.judged_build()
        out = self.physical("deploy", ["deploy", copy], self.timeouts["deploy"])
        return {**out, "digest": digest, "commit": commit}

    def _request_restart(self):
        return self.physical("restart", ["restart"], self.timeouts["restart"])

    def _request_replay(self):
        runs = [int(m.group(1)) for d in (self.state / "runs").iterdir() if (m := RUN_NAME.fullmatch(d.name))]
        run = self.state / "runs" / f"run-{max(runs, default=0) + 1}"
        out = self.physical("replay", ["replay", "--kind", "run", "--out", run], self.timeouts["replay"])
        res = read_json(run / "run-result.json")
        return {**out, "run": run.name, "digest": (res or {}).get("approved_digest"),
                "result": {k: v for k, v in (res or {}).items() if k in ("replay_id", "replay_finished",
                                                                          "figures_after_replay_end", "vm_hwm_kib",
                                                                          "threads_at_end", "vstatd_restarts")}}

    # ------------------------------------------------------------------------------------------ after-bench checks

    def _run_check(self, check):
        self.pick("check", check, CHECKS)
        run = self.last_run()
        if run is None:
            raise Refused("no replay yet; call request_replay first")
        if not (self.baseline / "baseline-result.json").is_file():
            raise Refused("the bench has no baseline; the bench owner records one")
        inputs = {"run_result": run / "run-result.json", "run_log": run / "run.jsonl",
                  "baseline_result": self.baseline / "baseline-result.json",
                  "baseline_log": self.baseline / "baseline.jsonl"}
        if CHECKS[check]:
            inputs["triage"] = self.triage
        hashes = {k: sha256(p) for k, p in inputs.items()}
        work = self.state / "work"
        clear(work)
        work.mkdir()
        results = work / "results"
        results.mkdir()
        cmd = [self.checks / f"{check}.sh", "--results", results, "--run", run, "--baseline", self.baseline]
        if CHECKS[check]:
            cmd += ["--triage", self.triage]
        log = self.state / "logs" / f"check-{check}.out"
        call_start = now()
        ro = [self.sample, run, self.baseline, *([self.triage.parent] if CHECKS[check] else [])]
        r = self.sandbox.run(cmd, log, self.timeouts["check"], ro=ro, rw=[work])
        verdict = VERDICTS.get(r["exit_status"], "ERROR")
        data, problem = self.judge(results, check, verdict, call_start, inputs, hashes)
        if r["outcome"] == "timeout" and not problem:
            problem = "the check timed out"
        dest = self.state / "results"
        for suffix in ("json", "log", "diff"):
            (dest / f"{check}.{suffix}").unlink(missing_ok=True)
        if problem:
            verdict = "ERROR"
            write_atomic(dest / f"{check}.json", json.dumps({
                "check": check, "verdict": "ERROR", "commit": None, "local": False, "started": call_start,
                "ended": now(), "summary": problem, "reasons": [f"bench server: {problem}"], "inputs": {},
                "details": {}}, indent=2) + "\n")
            write_atomic(dest / f"{check}.log", f"bench server: {problem}\n--- the check's output ---\n{tail(log)}")
        else:
            for suffix in ("json", "log", "diff"):
                blob = read_nofollow(results / f"{check}.{suffix}")
                if blob is not None:
                    write_atomic(dest / f"{check}.{suffix}", blob)
        clear(work)
        out = {**r, "check": check, "run": run.name, "verdict": verdict, "summary": tail(log, 2048)}
        out.update({"problem": problem} if problem else {"result": data})
        return out

    @staticmethod
    def judge(results, check, verdict, call_start, inputs, hashes):
        """The check's result and None, or None and why it cannot be published: it must be this call's, agree with
        the exit status, and have judged the run and baseline the server gave it, unchanged."""
        if not real_dir(results):
            return None, "the check replaced its results folder"
        data = read_json(results / f"{check}.json")
        if not data:
            return None, "the check wrote no result"
        started = data.get("started")
        if data.get("check") != check or not isinstance(started, str) or started < call_start:
            return None, "the result file is not this run's"
        if data.get("verdict") != verdict:
            return None, f"the result says {data.get('verdict')!r}, the exit status says {verdict}"
        if data.get("local"):
            return None, "the result was produced with --local"
        recorded = data.get("inputs")
        if not isinstance(recorded, dict) or not isinstance(data.get("details", {}), dict):
            return None, "the result is malformed"
        if verdict in ("PASS", "FAIL"):
            for name, path in inputs.items():
                inp = recorded.get(name)
                if not isinstance(inp, dict) or pathlib.Path(str(inp.get("path"))).resolve() != path.resolve():
                    return None, f"the result did not judge the server's {name} ({path})"
                if inp.get("sha256") != hashes[name] or sha256(path) != hashes[name]:
                    return None, f"{name} changed during the check"
        return data, None


def end_on_exit(service):
    """The server's exit handlers: on a normal exit and on SIGTERM, SIGHUP and SIGINT (an MCP client that goes away
    closes stdin and then terminates the server), end the session and exit at once, without waiting for the call in
    progress."""
    atexit.register(service.end_session)

    def on_signal(signum, _frame):
        service.end_session(f"the server got signal {signal.Signals(signum).name}")
        os._exit(128 + signum)
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, on_signal)
