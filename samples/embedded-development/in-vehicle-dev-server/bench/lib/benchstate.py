# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""State of the bench: the simulated supply, the target's state, approval requests and the action record.

Everything lives in one directory on the bench host, `$CC1_BENCH_STATE` (default `~/.cc1-bench`, mode 0700). The agents
never get it: they reach the bench through the bench MCP server (build plan item 5), which calls bench/cc1.sh. Only the
operator console (bench/console.py) and a scripted scenario change the supply; only a person at the console approves or
refuses a request (CC1-PN §8.1, §8.2; scenario page, section 4).

Target states: `off` (QEMU not running), `known`, `busy` (one action in progress) and `unknown` (an action was interrupted
or failed; only reads and a reconcile at the console until a person has checked it).
"""
import contextlib
import fcntl
import getpass
import json
import os
import pathlib
import secrets
import socket
import time
from datetime import datetime, timezone

VOLTAGE_MIN, VOLTAGE_MAX = 11.0, 14.8  # CC1-PN §8.1
# The actions that need the physical gate and a person's approval (CC1-PN §8.1; scenario page, section 3).
PHYSICAL = {"deploy": "Deploy a build", "restart": "Restart vstatd", "replay": "Start the drive replay"}


class GateError(Exception):
    pass


def timeout_s():
    return int(os.environ.get("CC1_APPROVAL_TIMEOUT_S", "300"))


def state_dir():
    d = pathlib.Path(os.environ.get("CC1_BENCH_STATE") or pathlib.Path.home() / ".cc1-bench")
    for sub in ("requests", "decisions", "builds"):
        (d / sub).mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def utc(t=None):
    return datetime.fromtimestamp(time.time() if t is None else t, timezone.utc).isoformat(timespec="milliseconds") \
        .replace("+00:00", "Z")


def who():
    tty = os.ttyname(0) if os.isatty(0) else "no tty"
    return f"{getpass.getuser()}@{socket.gethostname()} ({tty})"


def read_json(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    path = pathlib.Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=1) + "\n")
    os.replace(tmp, path)


def record(event, **fields):
    """Appends one entry to the action record, actions.jsonl. Nothing in the bench rewrites it."""
    line = json.dumps({"at": utc(), "event": event, **fields})
    with open(state_dir() / "actions.jsonl", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def records():
    p = state_dir() / "actions.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


@contextlib.contextmanager
def locked():
    with open(state_dir() / "target.lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


# ---- the simulated supply (CC1-PN §8.1, §8.2) ----

def supply():
    return read_json(state_dir() / "supply.json")


def set_supply(voltage=None, kl15=None, by=None):
    cur = supply() or {}
    if voltage is not None:
        voltage = float(voltage)
        if not 0.0 <= voltage <= 30.0:
            raise GateError("the simulated supply sets 0 to 30 V")
        cur["voltage_v"] = round(voltage, 2)
    if kl15 is not None:
        if kl15 not in ("on", "off"):
            raise GateError("KL15 is on or off")
        cur["kl15"] = kl15
    cur["set_at"], cur["set_by"] = utc(), by or who()
    write_json(state_dir() / "supply.json", cur)
    record("supply", voltage_v=cur.get("voltage_v"), kl15=cur.get("kl15"), by=cur["set_by"])
    return cur


def physical_check(action):
    """The physical gate. Returns (passed, reason)."""
    if action not in PHYSICAL:
        return True, "no physical precondition"
    s = supply()
    if not s or "voltage_v" not in s or "kl15" not in s:
        return False, "the supply has not been set at the operator console"
    v = s["voltage_v"]
    if not VOLTAGE_MIN <= v <= VOLTAGE_MAX:
        return False, f"supply {v:.2f} V is outside {VOLTAGE_MIN} to {VOLTAGE_MAX} V (CC1-PN §8.1)"
    if s["kl15"] != "on":
        return False, f"ignition KL15 is off; {PHYSICAL[action].lower()} needs KL15 on (CC1-PN §8.1)"
    return True, f"supply {v:.2f} V, KL15 on"


# ---- the target ----

def _alive(pid):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def target():
    p = state_dir() / "target.json"
    t = read_json(p, {"state": "off", "why": "the emulated CC-1 is not running"})
    if t.get("state") == "busy" and not _alive(int(t.get("pid", 0))):
        t = {"state": "unknown", "since": utc(),
             "why": f"{t.get('action')} of {t.get('digest', '')[:12]} was interrupted (request {t.get('request')})"}
        write_json(p, t)
        record("target", state="unknown", why=t["why"])
    return t


def set_target(state, why, **extra):
    write_json(state_dir() / "target.json", {"state": state, "why": why, "since": utc(), **extra})
    record("target", state=state, why=why, **{k: v for k, v in extra.items() if k != "pid"})


# ---- requests and decisions ----

def new_request(action, digest, detail=""):
    t = timeout_s()
    rid = time.strftime("%Y%m%dT%H%M%S") + f"-{action}-{secrets.token_hex(2)}"
    req = {"id": rid, "action": action, "what": PHYSICAL.get(action, action), "digest": digest, "detail": detail,
           "requested_at": utc(), "expires": time.time() + t, "timeout_s": t,
           "requested_by": os.environ.get("CC1_REQUESTER", "bench tools")}
    write_json(state_dir() / "requests" / f"{rid}.json", req)
    record("request", **{k: req[k] for k in ("id", "action", "digest", "detail", "timeout_s", "requested_by")})
    return req


def request(rid):
    return read_json(state_dir() / "requests" / f"{rid}.json")


def decision(rid):
    return read_json(state_dir() / "decisions" / f"{rid}.json")


def pending():
    now = time.time()
    out = []
    for p in sorted((state_dir() / "requests").glob("*.json")):
        r = read_json(p)
        if r and not decision(r["id"]):
            r["expired"] = now >= r["expires"]
            out.append(r)
    return out


def decide(rid, verdict, by, reason="", digest_prefix=None):
    r = request(rid)
    if not r:
        raise GateError(f"no request {rid}")
    if decision(rid):
        raise GateError(f"request {rid} has already been decided")
    if verdict == "approved":
        if time.time() >= r["expires"]:
            raise GateError(f"request {rid} has expired")
        if not digest_prefix or len(digest_prefix) < 6 or not r["digest"].startswith(digest_prefix.lower()):
            raise GateError("to approve, type at least the first 6 characters of the digest shown")
    elif verdict != "refused":
        raise GateError("a decision is approved or refused")
    dec = {"id": rid, "verdict": verdict, "action": r["action"], "digest": r["digest"], "by": by, "reason": reason,
           "at": utc()}
    path = state_dir() / "decisions" / f"{rid}.json"
    tmp = path.with_name(f".{rid}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dec) + "\n")
    try:
        os.link(tmp, path)  # exclusive: a request is decided once
    except FileExistsError:
        raise GateError(f"request {rid} has already been decided")
    finally:
        tmp.unlink(missing_ok=True)
    record("decision", id=rid, verdict=verdict, action=r["action"], digest=r["digest"], by=by, reason=reason)
    return dec


def wait_decision(rid, poll=0.2):
    r = request(rid)
    while True:
        dec = decision(rid)
        if dec:
            return dec
        if time.time() >= r["expires"]:
            try:
                return decide(rid, "refused", "bench (timeout)",
                              f"no answer at the operator console within {r['timeout_s']} s")
            except GateError:
                continue
        time.sleep(poll)


def authorize(action, digest, detail=""):
    """Target state, physical gate, a person's approval for this digest, the physical gate again.
    Returns the request ID; raises GateError when the action may not run."""
    if action not in PHYSICAL:
        raise GateError(f"{action} is not a physical action")
    t = target()
    if t["state"] != "known":
        raise GateError(f"the target is {t['state']}: {t['why']}. Only reads and a reconcile at the operator console")
    ok, why = physical_check(action)
    record("gate", action=action, digest=digest, stage="before the request", passed=ok, why=why)
    if not ok:
        raise GateError(f"physical gate: {why}")
    req = new_request(action, digest, detail)
    dec = wait_decision(req["id"])
    if dec["verdict"] != "approved":
        raise GateError(f"refused ({dec['by']}): {dec['reason'] or 'no reason given'}")
    if dec["digest"] != digest or dec["action"] != action:
        raise GateError("the approval is not for this action and digest")
    ok, why = physical_check(action)
    record("gate", action=action, digest=digest, stage="after the approval", passed=ok, why=why, id=req["id"])
    if not ok:
        raise GateError(f"physical gate after the approval: {why}")
    return req["id"]


def begin(rid, action, digest, pid):
    """Starts an approved action: one at a time, each approval used once."""
    with locked():
        t = target()
        if t["state"] == "busy":
            raise GateError(f"the target is busy: {t['why']} (one action at a time)")
        if t["state"] != "known":
            raise GateError(f"the target is {t['state']}: {t['why']}")
        r, dec = request(rid), decision(rid)
        if not r or not dec or dec["verdict"] != "approved" or r["action"] != action or r["digest"] != digest \
                or dec["digest"] != digest:
            raise GateError("no approval for this action and digest")
        try:
            os.close(os.open(state_dir() / "decisions" / f"{rid}.used", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            raise GateError(f"the approval {rid} has already been used")
        set_target("busy", f"{action} in progress", action=action, digest=digest, request=rid, pid=pid)


def end(rid, ok, detail=""):
    with locked():
        t = target()
        if t.get("state") != "busy" or t.get("request") != rid:
            record("action", id=rid, result="ok" if ok else "failed", detail=detail,
                   note="the target was not busy with this request")
            return
        record("action", id=rid, action=t["action"], digest=t["digest"], result="ok" if ok else "failed",
               detail=detail)
        set_target("known" if ok else "unknown", ("done: " if ok else "failed: ") + detail,
                   last_request=rid, last_digest=t["digest"])
