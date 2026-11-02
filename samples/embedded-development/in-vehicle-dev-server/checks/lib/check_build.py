#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""checks/build.sh: the cross build with the team's flags [TR §2.1] and the toolchain of [CC1-PN §7].

Configures a fresh build of the committed tree with the project's toolchain file and nothing else (the check passes
no sysroot or include path of its own) and builds `vstatd`. Then verifies from compile_commands.json that every file
was compiled by the cross compiler with the flags of TR §2.1 in effect (a later flag that undoes one counts), against
the CC-1 sysroot and without the unit tests' test double [CC1-PN §7.2-§7.3]; that no source switches warnings off;
and that `vstatd` is a 64-bit Arm executable linked against libsystemd. Strips it and records its SHA-256: the digest
a person approves at the operator console.
"""

import json
import pathlib
import shlex
import shutil
import subprocess
import sys

import common as c


def effective(args):
    """The flags in effect: for each kind, the last one given."""
    eff = {"opt": None, "fortify": None, "stack": None, "werror": False, "wall": False, "wextra": False}
    off = []
    for a in args:
        if a.startswith("-O"):
            eff["opt"] = a
        elif a.startswith("-D_FORTIFY_SOURCE"):
            eff["fortify"] = a
        elif a in ("-U_FORTIFY_SOURCE",) or a.startswith("-U_FORTIFY_SOURCE"):
            eff["fortify"] = None
        elif a.startswith("-fstack-protector") or a == "-fno-stack-protector":
            eff["stack"] = a
        elif a == "-Werror":
            eff["werror"] = True
        elif a == "-Wall":
            eff["wall"] = True
        elif a == "-Wextra":
            eff["wextra"] = True
        elif a == "-w" or a.startswith("-Wno-") or a.startswith("-Wno-error"):
            off.append(a)
    return eff, off


def flag_problems(entry, lim, tree):
    args = entry.get("arguments") or shlex.split(entry["command"])
    problems = []
    if not pathlib.Path(args[0]).name.endswith(lim["cross_compiler"]):
        problems.append(f"compiled by {args[0]}, not {lim['cross_compiler']}")
    eff, off = effective(args)
    want = {"opt": "-O2", "fortify": "-D_FORTIFY_SOURCE=2", "stack": "-fstack-protector-strong"}
    for k, v in want.items():
        if eff[k] != v:
            problems.append(f"{v} not in effect ({eff[k] or 'missing'})")
    for k, v in (("wall", "-Wall"), ("wextra", "-Wextra"), ("werror", "-Werror")):
        if not eff[k]:
            problems.append(f"missing {v}")
    if off:
        problems.append(f"warnings switched off: {' '.join(off)}")
    sysroots = [a.split("=", 1)[1] for a in args if a.startswith("--sysroot=")]
    sysroots += [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--sysroot"]
    if not sysroots or sysroots[-1].rstrip("/") != lim["sysroot"]:
        problems.append(f"not built against the CC-1 sysroot {lim['sysroot']} ({sysroots[-1] if sysroots else 'none'})")
    if any("tests/stubs" in a for a in args) or any("sd-daemon" in a for a in args):
        problems.append("uses the unit tests' test double (CC1-PN §7.3 is for the build server only)")
    return problems


def body(args, r):
    lim = c.limits()
    project = pathlib.Path(args.project).resolve()
    commit, why = c.judged_commit(project, args.local)
    if why:
        r.reason(why)
        return c.BLOCKED, "cannot judge the tree"
    r.data["commit"], r.data["local"] = commit, args.local
    work = pathlib.Path(args.results).resolve() / "work" / "build"
    shutil.rmtree(work, ignore_errors=True)
    tree = c.materialize(project, args.local, work / "tree")
    build = work / "build"
    toolchain = tree / "cmake" / "cc1-aarch64.cmake"
    r.input("toolchain_file", toolchain)
    r.data["tools"] = {"cmake": c.version("cmake"), "compiler": c.version(lim["cross_compiler"])}

    if c.run(["cmake", "-S", tree, "-B", build, "-G", "Ninja", f"-DCMAKE_TOOLCHAIN_FILE={toolchain}"], r.log) != 0:
        r.reason("cmake configuration failed; see build.log")
        return c.FAIL, "configuration failed"
    db = build / "compile_commands.json"
    entries = json.loads(db.read_text()) if db.is_file() else []
    if not any(pathlib.Path(e["file"]).resolve().is_relative_to(tree / "src") for e in entries):
        r.reason("no product source file in compile_commands.json (CMAKE_EXPORT_COMPILE_COMMANDS)")
        return c.FAIL, "nothing to check"
    if c.run(["ninja", "-C", build, "vstatd"], r.log) != 0:
        errors = [ln for ln in r.log.read_text().splitlines() if "error:" in ln or "fatal error" in ln]
        for ln in errors[:10]:
            r.reason(ln.replace(str(tree) + "/", ""))
        return c.FAIL, "cross build failed"

    # Only once it builds: a build that fails reports the compiler's own messages, as a person would see them.
    for e in entries:
        name = pathlib.Path(e["file"]).resolve()
        name = name.relative_to(tree) if name.is_relative_to(tree) else name
        for p in flag_problems(e, lim, tree):
            r.reason(f"{name}: {p}")
    for p in c.hiding_problems(tree, ("src",)):
        r.reason(p)
    r.data["details"]["translation_units"] = len(entries)
    if r.data["reasons"]:
        return c.FAIL, "the team's flags or toolchain are not in effect (TR §2.1, CC1-PN §7)"

    needed = subprocess.run(["aarch64-linux-gnu-readelf", "-d", build / "vstatd"], capture_output=True, text=True)
    if needed.returncode != 0 or f"[{lim['needed_library']}]" not in needed.stdout:
        r.reason(f"vstatd is not linked against {lim['needed_library']} (readiness via sd_notify, CC1-PN §4.2, "
                 f"§7.2)")
        return c.FAIL, "not linked against libsystemd"
    artifacts = pathlib.Path(args.results).resolve() / "artifacts"
    artifacts.mkdir(exist_ok=True)
    stripped = artifacts / "vstatd"
    if c.run(["aarch64-linux-gnu-strip", "-o", stripped, build / "vstatd"], r.log) != 0:
        r.reason("strip failed")
        return c.FAIL, "strip failed"
    kind = subprocess.run(["file", "-b", stripped], capture_output=True, text=True).stdout.strip()
    r.data["details"].update({"artifact": str(stripped), "digest": c.sha256(stripped),
                              "size_bytes": stripped.stat().st_size, "file": kind})
    r.input("artifact", stripped)
    if "ELF 64-bit" not in kind or "aarch64" not in kind:
        r.reason(f"not a 64-bit Arm ELF: {kind}")
        return c.FAIL, "wrong target"
    return c.PASS, f"vstatd sha256 {r.data['details']['digest']}"


def add_args(p):
    p.add_argument("--project", default=".", help="the vstatd project (a git work tree)")
    p.add_argument("--local", action="store_true", help="judge a dirty tree; release.sh rejects the result")


if __name__ == "__main__":
    sys.exit(c.main("build", "n/a", add_args, body))
