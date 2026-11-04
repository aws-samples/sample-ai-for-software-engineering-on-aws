# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""The `build` service: configure, build, run a check and read results, with the guardrails of the scenario page
(section 4). This module has no MCP dependency; `server.py` exposes it over MCP and the tests call it directly.

Configuring and building a project runs the project's own code (CMake scripts, build rules, tests). So everything
that touches the agents' content runs in a sandbox: a container with no network, a read-only root, no capabilities,
a fresh home, and only the mounts the call needs. Even git runs on the agents' work tree only in the sandbox, because
a repository's config can run commands. The server's state (logs, published results, repair count, audit log) is
never mounted where the project's code could write it.

Guardrails, enforced here whatever the agent session allows:
- deny by default: a call runs only when the server's role grants the tool's permission class;
- closed arguments: profiles, targets, checks and log kinds come from fixed lists;
- checks run with fixed arguments on a clean clone of the committed HEAD, never `--local`; a result is published only
  when it is this run's and agrees with the check's exit status, otherwise an ERROR record replaces it;
- bounded repair: a failed cross configure, cross build or build check counts; a passed build check clears the count;
  after the first attempt and the retries TR §5.1 allows have failed, they are refused until a person resets it;
- every call is audited, refusals and errors included;
- one call at a time; timeouts kill the sandbox; nothing is retried automatically.
"""

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
import shlex
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import tomllib

READ_ONLY, CONTROLLED_WRITE = "read-only", "controlled-write"
CLASSES = (READ_ONLY, CONTROLLED_WRITE)
PROFILES = {
    "cross": ["-DCMAKE_TOOLCHAIN_FILE={workspace}/cmake/cc1-aarch64.cmake"],
    "host": [],
    "tsan": ["-DVSTATD_SANITIZE=thread"],
    "asan": ["-DVSTATD_SANITIZE=address,undefined"],
}
TARGETS = ("vstatd", "vstatd_tests", "all")
# Checks the agents may run, and whether each reads the approved triage. The after-deploy checks belong to `bench`.
CHECKS = {"build": False, "static": True, "unit": True, "size": False, "trace": True, "release": True}
SYSROOT_CHECKS = ("build", "static")  # the checks that configure the cross profile
LOG_KINDS = ("configure", "build")
TOOLS = {
    "workspace_status": (READ_ONLY, ()),
    "configure": (CONTROLLED_WRITE, ("profile",)),
    "build": (CONTROLLED_WRITE, ("profile", "target")),
    "run_check": (CONTROLLED_WRITE, ("check",)),
    "read_result": (READ_ONLY, ("check",)),
    "read_log": (READ_ONLY, ("kind", "profile")),
}
OPTIONAL = {("build", "target")}
VERDICTS = {0: "PASS", 1: "FAIL", 2: "USAGE", 3: "BLOCKED"}
TAIL_BYTES = 8192
SAFE_GIT = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.attributesFile=/dev/null"]
DOCKER_CLIENT_ENV = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH",
                     "DOCKER_TLS_VERIFY", "XDG_RUNTIME_DIR")


class Refused(Exception):
    """The call is not allowed; nothing was run."""


class ConfigError(Exception):
    """The server configuration is unsafe or incomplete; the server does not start."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_nofollow(path, limit=16 * 1024 * 1024, start=None):
    """Bytes of a regular file the sandbox may have written, or None. Never follows a symlink at the last step and
    never blocks on a FIFO. `start=None` reads from the start; otherwise from `limit` bytes before the end."""
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


def real_dir(path):
    """A directory, not a symlink to one."""
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
    """Removes a folder the sandbox wrote, also when the project's code made parts of it unreadable."""
    if os.path.lexists(path) and not real_dir(path):
        os.unlink(path)
    if real_dir(path):
        os.chmod(path, 0o700)
        for root, dirs, _ in os.walk(path):
            for d in dirs:
                p = os.path.join(root, d)
                if real_dir(p):
                    os.chmod(p, 0o700)
        shutil.rmtree(path)


def private_group(gid):
    """The server user's own group, with no other members: writable by it means writable by the server only."""
    if gid != os.getgid():
        return False
    try:
        members = set(grp.getgrgid(gid).gr_mem)
        me = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return False
    # Users whose primary group it is; a directory service that does not enumerate its accounts can hide some, so
    # keep the server's group to itself (useradd --system does).
    members |= {u.pw_name for u in pwd.getpwall() if u.pw_gid == gid}
    return members <= {me}


def check_trusted(path, name, include_self=True):
    """Refuses a path that someone other than root or the server's user could replace or redirect: every folder from
    the root down must be theirs and not writable by others (a sticky folder may hold one of theirs)."""
    path = pathlib.Path(path).resolve()
    chain = [*reversed(path.parents), path] if include_self else list(reversed(path.parents))
    chain = [d for d in chain if os.path.lexists(d)]  # a path still to be made is as safe as its parent
    for i, d in enumerate(chain):
        st = os.lstat(d)
        trusted = (0, os.getuid())
        if st.st_uid not in trusted:
            raise ConfigError(f"paths.{name}: {d} belongs to uid {st.st_uid}, not root or the server's user")
        other = st.st_mode & stat.S_IWOTH or (st.st_mode & stat.S_IWGRP and not private_group(st.st_gid))
        if other:
            nxt = chain[i + 1] if i + 1 < len(chain) else None
            if not (st.st_mode & stat.S_ISVTX and nxt is not None and os.lstat(nxt).st_uid in trusted):
                raise ConfigError(f"paths.{name}: {d} is writable by other users, who could replace {path}")


def check_tree(root, name):
    """Refuses a folder whose content (checks, triage) someone other than root or the server's user could change."""
    trusted = (0, os.getuid())

    def unreadable(e):
        raise ConfigError(f"paths.{name}: cannot check {e.filename}: {e.strerror}")
    for dirpath, dirs, files in os.walk(root, onerror=unreadable):
        for entry in [dirpath, *(os.path.join(dirpath, n) for n in dirs + files)]:
            st = os.lstat(entry)
            if st.st_uid not in trusted:
                raise ConfigError(f"paths.{name}: {entry} belongs to uid {st.st_uid}, not root or the server's user")
            if not stat.S_ISLNK(st.st_mode) and (
                    st.st_mode & stat.S_IWOTH or (st.st_mode & stat.S_IWGRP and not private_group(st.st_gid))):
                raise ConfigError(f"paths.{name}: {entry} is writable by other users")


def bundle_head(path):
    """The commit of HEAD in a git bundle, read from its header in Python (no git runs on the agents' data)."""
    data = read_nofollow(path, 64 * 1024)
    if not data or b"\n\n" not in data:
        return None
    lines = data.split(b"\n\n", 1)[0].decode(errors="replace").split("\n")
    if lines[0] not in ("# v2 git bundle", "# v3 git bundle"):
        return None
    heads = [ln.split(" ", 1) for ln in lines[1:] if ln and ln[0] not in "-@"]
    found = [sha for sha, *ref in heads if ref == ["HEAD"] and re.fullmatch(r"[0-9a-f]{40}([0-9a-f]{24})?", sha)]
    return found[0] if len(found) == 1 else None


class Sandbox:
    """Runs a command in a container started for that one call: no network, read-only root, no capabilities, no new
    privileges, a fresh home, at most 1024 processes and only the given mounts, which keep their host paths.
    `runner = "none"` runs the command directly, for the server's own tests only."""

    def __init__(self, cfg, env_path, label):
        self.runner = cfg.get("runner", "docker")
        self.image = str(cfg.get("image", "vstatd-build"))
        self.user = str(cfg.get("user", f"{os.getuid()}:{os.getgid()}"))
        if self.user.split(":")[0] in ("0", "root"):
            raise ConfigError("sandbox.user must not be root")
        # Extra docker options per check, e.g. unit = ["--security-opt", "seccomp=unconfined"] for TSan's setarch -R.
        self.check_args = {str(k): [str(a) for a in v] for k, v in cfg.get("check_args", {}).items()}
        unknown = sorted(set(self.check_args) - set(CHECKS))
        if unknown:
            raise ConfigError(f"sandbox.check_args: unknown checks {unknown}")
        self.limits = [f"--{k}={cfg[k]}" for k in ("memory", "cpus") if k in cfg]
        self.docker_host = cfg.get("docker_host")  # e.g. rootless Docker's socket, which sudo's clean environment loses
        self.env_path = env_path
        self.label = f"buildserver.state={label}"
        self.names = itertools.count()
        if self.runner == "none" and os.environ.get("BUILDSERVER_UNSANDBOXED_FOR_TESTS") != "1":
            raise ConfigError('sandbox.runner = "none" runs project code without isolation; it is for the server\'s '
                              "own tests only (set BUILDSERVER_UNSANDBOXED_FOR_TESTS=1 there)")
        if self.runner not in ("docker", "none"):
            raise ConfigError(f"sandbox.runner must be docker (or none for tests), not {self.runner!r}")

    def env(self):
        return {"PATH": self.env_path, "HOME": "/tmp/home", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}

    def client_env(self):
        """What the docker client needs to find its daemon (rootless included); none of it reaches the container."""
        env = {k: os.environ[k] for k in DOCKER_CLIENT_ENV if k in os.environ}
        env.setdefault("PATH", "/usr/bin:/bin")
        if self.docker_host:
            env["DOCKER_HOST"] = str(self.docker_host)
        return env

    def argv(self, cmd, name, ro=(), rw=(), workdir=None, extra=()):
        full = ["docker", "run", "--rm", "--init", "--name", name, "--label", self.label, "--network", "none",
                "--read-only", "--tmpfs", "/tmp:rw,exec,size=1g", "--user", self.user, "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--pids-limit", "1024", *self.limits, *extra]
        for k, v in self.env().items():
            full += ["-e", f"{k}={v}"]
        for mounts, flag in ((ro, ",readonly"), (rw, "")):
            for p in mounts:
                src, dst = (str(p[0]), str(p[1])) if isinstance(p, tuple) else (str(p), str(p))
                if any(c in src + dst for c in ",\n=") or not pathlib.Path(src).exists():
                    raise RuntimeError(f"cannot mount {src}: missing, or a comma, '=' or newline in its path")
                full += ["--mount", f"type=bind,source={src},target={dst}{flag}"]
        if workdir:
            full += ["-w", str(workdir)]
        return full + [self.image, "sh", "-c", 'mkdir -p "$HOME" && exec "$@"', "sandbox", *map(str, cmd)]

    def reap(self):
        """Removes containers left by a server of this state that died mid-call; the caller holds the lock."""
        if self.runner != "docker":
            return
        ps = subprocess.run(["docker", "ps", "-aq", "--filter", f"label={self.label}"], capture_output=True,
                            text=True, env=self.client_env(), timeout=60)
        if ps.returncode != 0:
            raise RuntimeError(f"docker ps failed: {ps.stderr.strip()[:300]}")
        ids = ps.stdout.split()
        if ids:
            rm = subprocess.run(["docker", "rm", "-f", *ids], capture_output=True, text=True, env=self.client_env(),
                                timeout=60)
            if rm.returncode != 0:
                raise RuntimeError(f"cannot remove containers a crashed server left: {rm.stderr.strip()[:300]}")

    def run(self, cmd, log, timeout, ro=(), rw=(), workdir=None, extra=()):
        """`ro` and `rw` are host paths, mounted at the same path; an `ro` entry may be (host path, container path)."""
        name = f"buildserver-{os.getpid()}-{next(self.names)}"
        home = None
        if self.runner == "docker":
            full, run_env, cwd = self.argv(cmd, name, ro, rw, workdir, extra), self.client_env(), None
        else:
            home = tempfile.mkdtemp(prefix="buildserver-home-")
            full, run_env, cwd = list(map(str, cmd)), {**self.env(), "HOME": home}, workdir
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(f"$ {shlex.join(map(str, cmd))}\n")
                f.flush()
                try:
                    proc = subprocess.Popen(full, cwd=cwd, env=run_env, stdout=f, stderr=subprocess.STDOUT,
                                            start_new_session=True)
                except FileNotFoundError as e:
                    f.write(f"{e}\n")
                    return {"outcome": "error", "exit_status": 127}
                try:
                    rc = proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    if self.runner == "docker":
                        subprocess.run(["docker", "kill", name], capture_output=True, env=run_env, timeout=60)
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, 9)
                    proc.wait()
                    f.write(f"\n[killed after {timeout} s; not retried]\n")
                    return {"outcome": "timeout", "exit_status": None}
            return {"outcome": "ok" if rc == 0 else "failed", "exit_status": rc}
        finally:
            if home:
                shutil.rmtree(home, ignore_errors=True)


class BuildService:
    def __init__(self, config_path, role):
        config_path = pathlib.Path(config_path).resolve()
        cfg = tomllib.loads(config_path.read_text())
        try:
            p = cfg["paths"]
            relative = [k for k in ("workspace", "state", "triage", "checks", "sysroot")
                        if k in p and not pathlib.Path(str(p[k])).is_absolute()]
            if relative:  # they would resolve against the caller's working directory
                raise ConfigError(f"paths {relative} must be absolute")
            self.workspace = pathlib.Path(p["workspace"]).resolve()
            self.state = pathlib.Path(p["state"]).resolve()
            self.triage = pathlib.Path(p["triage"]).resolve()
            self.checks = pathlib.Path(p["checks"]).resolve()
            self.sysroot = pathlib.Path(p.get("sysroot", "/opt/cc1-sysroot")).resolve()
        except KeyError as e:
            raise ConfigError(f"missing paths.{e.args[0]} in {config_path}") from None
        if not (self.workspace / ".git").exists():
            raise ConfigError(f"workspace {self.workspace} is not a git work tree")
        for name in ("state", "triage", "checks", "sysroot"):
            if inside(getattr(self, name), self.workspace):
                raise ConfigError(f"paths.{name} lies inside the agents' work tree; the agents could change it")
        if inside(config_path, self.workspace):
            raise ConfigError("the configuration lies inside the agents' work tree; the agents could change it")
        if inside(self.workspace, self.state) or inside(self.triage, self.state):
            raise ConfigError("paths.workspace and paths.triage must lie outside paths.state")
        self.sample = self.checks.parent
        if inside(self.workspace, self.sample) or inside(self.sample, self.workspace):
            raise ConfigError("paths.workspace and the sample (the parent of paths.checks) must not contain each other")
        if inside(self.state, self.sample) or inside(self.state, self.triage.parent):
            raise ConfigError("paths.state must lie outside the sample and the triage folder, which checks can read")
        if not self.triage.parent.is_dir():
            raise ConfigError(f"the folder of paths.triage, {self.triage.parent}, does not exist")
        self.state.mkdir(parents=True, exist_ok=True)
        # The agents own the work tree, not the folders above it; everything else is the server's or root's.
        check_trusted(self.workspace, "workspace", include_self=False)
        for name, path in (("state", self.state), ("triage", self.triage.parent), ("checks", self.sample),
                           ("sysroot", self.sysroot), ("config", config_path)):
            check_trusted(path, name)
        check_trusted(pathlib.Path(__file__).resolve().parent, "the server's own code")
        check_tree(self.sample, "checks")
        check_tree(self.triage.parent, "triage")
        self.mounted = {p: os.stat(p)[1:3] for p in (self.workspace, self.state, self.triage.parent, self.sample,
                                                      self.sysroot) if p.exists()}
        for d in ("builds", "logs", "results"):
            (self.state / d).mkdir(exist_ok=True)
        self.audit_log = self.state / "audit.jsonl"
        self.repair_file = self.state / "repair.json"
        self.role = role
        granted = cfg.get("roles", {}).get(role, {}).get("classes", [])
        unknown = [c for c in granted if c not in CLASSES]
        if unknown:
            raise ConfigError(f"role {role}: unknown permission classes {unknown}")
        self.granted = set(granted)
        self.timeouts = {"status": 60, "snapshot": 300, "configure": 600, "build": 1800, "check": 3600,
                         **cfg.get("timeouts", {})}
        env_path = cfg.get("environment", {}).get("path", "/usr/local/bin:/usr/bin:/bin")
        label = hashlib.sha256(str(self.state).encode()).hexdigest()[:16]
        self.sandbox = Sandbox(cfg.get("sandbox", {}), env_path, label)
        tools = cfg.get("tools", {})
        self.cmake, self.ninja = tools.get("cmake", "cmake"), tools.get("ninja", "ninja")
        self.git = tools.get("git", "git")
        try:
            limits = json.loads((self.checks / "limits.json").read_text())
            self.repair_limit = int(limits["repair_rounds"]["value"]["cross_build"])
            # Where the toolchain file and checks/build.sh expect the sysroot; the sandbox mounts paths.sysroot there.
            self.sysroot_mount = (self.sysroot, pathlib.Path(limits["sysroot"]["value"]))
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise ConfigError(f"cannot read repair_rounds.cross_build and sysroot from "
                              f"{self.checks / 'limits.json'}: {e}") from None
        self.lock = threading.Lock()
        self.lock_path = self.state / "lock"

    @contextlib.contextmanager
    def exclusive(self):
        """The server's lock across threads and processes (another server, the admin command)."""
        with self.lock:
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o640)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)

    def check_mounts(self):
        """The folders mounted into a sandbox are still the ones checked at start, not something swapped in."""
        for path, ident in self.mounted.items():
            try:
                same = os.stat(path)[1:3] == ident and real_dir(path)
            except OSError:
                same = False
            if not same:
                raise Refused(f"{path} changed since the server started; a person checks the build server")

    # ------------------------------------------------------------------------------------------ audit and calls

    def audit(self, entry):
        line = json.dumps({"t": now(), "role": self.role, **entry}, ensure_ascii=False, sort_keys=True, default=repr)
        fd = os.open(self.audit_log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o640)
        try:
            os.write(fd, (line + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def malformed(tool, args):
        """Why a call is not well formed, or None. Decided without the lock, so a refusal never waits for a build."""
        cls, params = TOOLS.get(tool, (None, ())) if isinstance(tool, str) else (None, ())
        if cls is None:
            return "unknown tool"
        extra = sorted(set(args) - set(params))
        missing = [p for p in params if p not in args and (tool, p) not in OPTIONAL]
        wrong = sorted(k for k, v in args.items() if not isinstance(v, str))
        return (f"unexpected arguments {extra}" if extra else f"missing arguments {missing}" if missing else
                f"arguments that are not strings {wrong}" if wrong else None)

    def call(self, tool, **args):
        """One tool call through the guardrails. Audited before and after; raises Refused, or RuntimeError on an
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
            try:
                self.check_mounts()
                self.sandbox.reap()
                result = getattr(self, "_" + tool)(**args)
            except Refused as e:
                self.audit({**entry, "outcome": "refused", "detail": str(e)})
                raise
            except Exception as e:  # noqa: BLE001 - audited, then reported without internals
                self.audit({**entry, "outcome": "error", "detail": f"{type(e).__name__}: {e}"})
                raise RuntimeError(f"{tool} failed on the server; see the audit log") from e
            self.audit({**entry, "outcome": result.get("outcome", "ok"), "exit_status": result.get("exit_status"),
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        **({"verdict": result["verdict"]} if "verdict" in result else {}),
                        **({"digest": result["digest"]} if result.get("digest") else {})})
            return result

    @staticmethod
    def pick(name, value, allowed):
        if not isinstance(value, str) or value not in allowed:
            raise Refused(f"{name} must be one of {', '.join(allowed)}")
        return value

    # ------------------------------------------------------------------------------------------ repair count

    def repair_state(self, strict=True):
        if not os.path.lexists(self.repair_file):
            return {"cross_build": {"failures_in_a_row": 0, "total_failures": 0}}
        try:
            state = json.loads(read_nofollow(self.repair_file) or b"")
            c = state["cross_build"]
            if not (isinstance(c["failures_in_a_row"], int) and isinstance(c["total_failures"], int)):
                raise ValueError("counts are not integers")
            return state
        except (ValueError, KeyError, TypeError) as e:
            if strict:
                raise Refused(f"repair count unreadable ({e}); a person resets it "
                              f"(python -m buildserver.admin reset-repair)") from None
            return {"cross_build": {"failures_in_a_row": 0, "total_failures": 0}}

    def save_repair(self, state):
        state["cross_build"]["limit_retries"] = self.repair_limit
        text = json.dumps(state, indent=2) + "\n"
        write_atomic(self.repair_file, text)
        write_atomic(self.state / "results" / "repair-rounds.json", text)

    def charge_cross_attempt(self):
        """Refuses past the bound; otherwise counts this attempt as a failure until it succeeds (fail closed)."""
        state = self.repair_state()
        c = state["cross_build"]
        if c["failures_in_a_row"] > self.repair_limit:
            raise Refused(f"cross attempts failed {c['failures_in_a_row']} times in a row: the first attempt and "
                          f"the {self.repair_limit} retries of TR §5.1. A person decides, then resets the count "
                          f"(python -m buildserver.admin reset-repair)")
        c["failures_in_a_row"] += 1
        c["total_failures"] += 1
        self.save_repair(state)
        return state

    def settle_cross_attempt(self, state, outcome):
        """`failed` keeps the charge; `succeeded` (a configure or build the project's own scripts call successful)
        takes it back but clears nothing; `passed` (checks/build.sh judged the committed HEAD PASS) clears the count."""
        c = state["cross_build"]
        if outcome in ("succeeded", "passed"):
            c["failures_in_a_row"] = 0 if outcome == "passed" else c["failures_in_a_row"] - 1
            c["total_failures"] -= 1
        self.save_repair(state)
        return {"failures_in_a_row": c["failures_in_a_row"], "limit_retries": self.repair_limit}

    # ------------------------------------------------------------------------------------------ tools

    def _workspace_status(self):
        log = self.state / "logs" / "status.log"
        g = f"{shlex.join([self.git, *SAFE_GIT, '-c', 'safe.directory=*', '-C', str(self.workspace)])}"
        # Git's warnings would shift the lines, so only standard output reaches the log.
        r = self.sandbox.run(["sh", "-c", f"{g} rev-parse HEAD 2>/dev/null && {g} rev-parse --abbrev-ref HEAD "
                                          f"2>/dev/null && {g} status --porcelain 2>/dev/null"], log,
                             self.timeouts["status"], ro=[self.workspace])
        lines = (read_nofollow(log, 256 * 1024) or b"").decode(errors="replace").splitlines()[1:]
        if r["outcome"] != "ok":
            why = "timed out" if r["outcome"] == "timeout" else "no commit, or not a git work tree"
            return {**r, "head": "", "branch": "", "changes": [], "problem": why}
        return {**r, "head": lines[0] if lines else "", "branch": lines[1] if len(lines) > 1 else "",
                "changes": lines[2:202]}

    def _cross(self, profile, run):
        """Runs a configure or build of a profile; for cross, charged as a repair attempt."""
        charged = self.charge_cross_attempt() if profile == "cross" else None
        r = run()
        if charged:
            r["repair"] = self.settle_cross_attempt(charged, "succeeded" if r["outcome"] == "ok" else "failed")
        return r

    def _configure(self, profile):
        self.pick("profile", profile, PROFILES)
        bdir = self.state / "builds" / profile
        clear(bdir)
        bdir.mkdir()
        args = [a.format(workspace=self.workspace) for a in PROFILES[profile]]
        log = self.state / "logs" / f"{profile}.configure.log"
        ro = [self.workspace, *([self.sysroot_mount] if profile == "cross" else [])]
        r = self._cross(profile, lambda: self.sandbox.run(
            [self.cmake, "-S", self.workspace, "-B", bdir, "-G", "Ninja", *args], log, self.timeouts["configure"],
            ro=ro, rw=[bdir]))
        return {**r, "profile": profile, "log_tail": tail(log)}

    def _build(self, profile, target="all"):
        self.pick("profile", profile, PROFILES)
        self.pick("target", target, TARGETS)
        bdir = self.state / "builds" / profile
        if not real_dir(bdir) or read_nofollow(bdir / "build.ninja", 1) is None:
            raise Refused(f"profile {profile} is not configured; call configure first")
        log = self.state / "logs" / f"{profile}.build.log"
        ro = [self.workspace, *([self.sysroot_mount] if profile == "cross" else [])]
        r = self._cross(profile, lambda: self.sandbox.run(
            [self.ninja, "-C", bdir] + ([] if target == "all" else [target]), log, self.timeouts["build"],
            ro=ro, rw=[bdir]))
        return {**r, "profile": profile, "target": target, "log_tail": tail(log)}

    def _snapshot_head(self, run):
        """A clean clone of the work tree's HEAD. The work tree's own git config can run commands, so git runs on it
        only in the sandbox, where it writes a bundle of HEAD; a second sandbox clones the bundle into `run/`. The
        server itself only reads the bundle's header (git's SECURITY notes: never run git on an untrusted .git)."""
        snap = self.state / "snap"
        clear(snap)
        snap.mkdir()
        bundle, log = snap / "head.bundle", self.state / "logs" / "snapshot.log"
        g = [self.git, *SAFE_GIT, "-c", "safe.directory=*"]
        r = self.sandbox.run([*g, "-C", self.workspace, "bundle", "create", bundle, "HEAD"], log,
                             self.timeouts["snapshot"], ro=[self.workspace], rw=[snap])
        head = bundle_head(bundle) if r["outcome"] == "ok" else None
        if not head:
            raise Refused(f"could not take the committed HEAD of the work tree; is there a commit?\n{tail(log, 1024)}")
        project = run / "project"
        q = shlex.join
        script = " && ".join([
            q([*g, "init", "-q", "-b", "judged", str(project)]),
            q([*g, "-C", str(project), "fetch", "-q", "--no-tags", "--update-head-ok", str(bundle),
               "+HEAD:refs/heads/judged"]),
            q([*g, "-C", str(project), "reset", "-q", "--hard", "judged"]),
            q([*g, "-C", str(project), "config", "user.name", "build server"]),
            q([*g, "-C", str(project), "config", "user.email", "build-server@example.invalid"])])
        r = self.sandbox.run(["sh", "-c", script], self.state / "logs" / "clone.log", self.timeouts["snapshot"],
                             ro=[snap], rw=[run])
        clear(snap)
        if r["outcome"] != "ok":
            raise RuntimeError(f"cloning the committed HEAD failed: {tail(self.state / 'logs' / 'clone.log', 1024)}")
        return project, head

    def owned(self, check):
        """The files of the results folder that belong to a check: its result, log and diff, its work folder and,
        for build, the artifacts. Paths relative to the results folder."""
        return ([f"{check}.json", f"{check}.log", f"{check}.diff", f"work/{check}"] +
                (["artifacts"] if check == "build" else []))

    def drop(self, base, check):
        for rel in self.owned(check):
            p = base / rel
            if real_dir(p):
                clear(p)
            elif os.path.lexists(p):
                os.unlink(p)

    def _run_check(self, check):
        self.pick("check", check, CHECKS)
        run = self.state / "run"
        clear(run)
        run.mkdir()
        project, head = self._snapshot_head(run)
        results = run / "results"
        shutil.copytree(self.state / "results", results)
        self.drop(results, check)
        cmd = [self.checks / f"{check}.sh", "--project", project, "--results", results]
        if CHECKS[check]:
            cmd += ["--triage", self.triage]
        charged = self.charge_cross_attempt() if check == "build" else None
        log = self.state / "logs" / f"check-{check}.out"
        call_start = now()
        ro = [self.sample, self.triage.parent, *([self.sysroot_mount] if check in SYSROOT_CHECKS else [])]
        r = self.sandbox.run(cmd, log, self.timeouts["check"], ro=ro, rw=[run], workdir=run,
                             extra=self.sandbox.check_args.get(check, ()))
        verdict = VERDICTS.get(r["exit_status"], "ERROR")
        data, problem = self.judge(results, check, verdict, call_start, head)
        if r["outcome"] == "timeout" and not problem:
            problem = "the check timed out"
        if problem:
            verdict = "ERROR"
            self.record_error(check, head, problem, call_start, log)
        else:
            self.publish(results, check, data)
        out = {**r, "check": check, "commit": head, "verdict": verdict, "summary": tail(log, 2048)}
        if problem:
            out["problem"] = problem
        else:
            out["result"] = data
            digest = (data.get("details") or {}).get("digest")
            if isinstance(digest, str):
                out["digest"] = digest
        if charged:
            out["repair"] = self.settle_cross_attempt(charged, "passed" if verdict == "PASS" else "failed")
        return out

    @staticmethod
    def judge(results, check, verdict, call_start, head):
        """The run's result and None, or None and why it cannot be published."""
        if not real_dir(results):
            return None, "the check replaced its results folder"
        try:
            data = json.loads(read_nofollow(results / f"{check}.json") or b"")
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return None, "the check wrote no result"
        started = data.get("started")
        if data.get("check") != check or not isinstance(started, str) or started < call_start:
            return None, "the result file is not this run's"
        if data.get("verdict") != verdict:
            return None, f"the result says {data.get('verdict')!r}, the exit status says {verdict}"
        if data.get("commit") != head and not (data.get("commit") is None and verdict in ("BLOCKED", "USAGE")):
            return None, f"the result judged {data.get('commit')!r}, not HEAD {head}"
        if not isinstance(data.get("inputs", {}), dict) or not isinstance(data.get("details", {}), dict):
            return None, "the result is malformed"
        return data, None

    def publish(self, results, check, data):
        """Copies this check's own files out of the finished run (the sandbox is gone, nothing races the copy): its
        result, log and diff, and the inputs it recorded inside its own part of the results folder (for build, the
        artifact and the toolchain file) when their content still matches the recorded sha256. Whatever this check
        published before is removed first, so nothing stale stays next to the new result."""
        dest = self.state / "results"
        self.drop(dest, check)
        files = {rel: read_nofollow(results / rel) for rel in self.owned(check)[:3]}
        folders = self.owned(check)[3:]
        for inp in data.get("inputs", {}).values():
            if not isinstance(inp, dict) or not isinstance(inp.get("path"), str):
                continue
            rel = pathlib.Path(os.path.relpath(os.path.normpath(inp["path"]), results))
            if rel.parts[0] not in ("work", "artifacts") or not any(str(rel).startswith(f + "/") for f in folders):
                continue
            if all(real_dir(results.joinpath(*rel.parts[:i])) for i in range(1, len(rel.parts))):
                blob = read_nofollow(results / rel, limit=256 * 1024 * 1024)
                if blob is not None and hashlib.sha256(blob).hexdigest() == inp.get("sha256"):
                    files[str(rel)] = blob
        for rel, blob in files.items():
            if blob is not None:
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                write_atomic(dest / rel, blob)

    def record_error(self, check, head, problem, call_start, log):
        """Replaces what this check published with an ERROR record written by the server."""
        dest = self.state / "results"
        self.drop(dest, check)
        record = {"check": check, "verdict": "ERROR", "commit": head, "local": False, "started": call_start,
                  "ended": now(), "summary": problem, "reasons": [f"build server: {problem}"], "inputs": {},
                  "details": {}}
        write_atomic(dest / f"{check}.json", json.dumps(record, indent=2) + "\n")
        write_atomic(dest / f"{check}.log", f"build server: {problem}\n--- the check's output ---\n{tail(log)}")

    def _read_result(self, check):
        self.pick("check", check, CHECKS)
        try:
            data = json.loads(read_nofollow(self.state / "results" / f"{check}.json") or b"")
        except ValueError:
            data = None
        return {"check": check, "result": data, "log_tail": tail(self.state / "results" / f"{check}.log")}

    def _read_log(self, kind, profile):
        self.pick("kind", kind, LOG_KINDS)
        self.pick("profile", profile, PROFILES)
        return {"kind": kind, "profile": profile, "log_tail": tail(self.state / "logs" / f"{profile}.{kind}.log")}
