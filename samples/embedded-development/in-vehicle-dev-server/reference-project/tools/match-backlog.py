#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Compare an analyser run with the findings backlog.

    tools/match-backlog.py build-cross/analysis ../knowledge/findings-backlog.md

Reads cppcheck.txt and clang-tidy.txt written by tools/run-analysers.sh, maps every finding to the function that
contains it, and pairs it with the backlog row of the same tool, check, file, function and message. A backlog message
may end with a note such as (`fcntl`): the note is not part of the analyser's text, and the source line of the finding
must contain it. Prints one table row per finding and exits non-zero when a finding has no row, a row has no finding,
or a row matches more than one finding.
"""

import pathlib
import re
import sys

CPPCHECK = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+): (?P<sev>\w+): (?P<check>[\w-]+): (?P<msg>.*)$")
TIDY = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+): (?:warning|error): (?P<msg>.*) \[(?P<check>[\w.,-]+)\]$")
NOTE = re.compile(r"^(?P<msg>.*?) \(`(?P<note>[^`]+)`\)$")
DEF = re.compile(r"^(?!namespace|class|struct|enum|using|template|static_assert|#|//|constexpr|inline)"
                 r"(?:[A-Za-z_][\w:<>,*& ]*?[\s*&])?(?P<name>(?:[A-Za-z_]\w*::)*~?[A-Za-z_]\w*)\s*\(")
CLASS = re.compile(r"^\s*(?:class|struct)\s+(?P<name>\w+)\b[^;]*$")
METHOD = re.compile(r"\b(?:explicit\s+)?(?P<name>~?[A-Za-z_]\w*)\s*\(")


def strip_code(line):
    line = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
    line = re.sub(r"'(?:\\.|[^'\\])*'", "''", line)
    return line.split("//", 1)[0]


def functions_of_source(lines):
    """Line number -> enclosing function, for definitions that start in column 0."""
    owner = {}
    i = 0
    while i < len(lines):
        m = DEF.match(lines[i])
        if not m or lines[i].rstrip().endswith(";") or "=" in lines[i].split("(", 1)[0]:
            i += 1
            continue
        name = m.group("name")
        depth, started, j = 0, False, i
        while j < len(lines):
            code = strip_code(lines[j])
            if not started and code.rstrip().endswith(";") and "{" not in code:
                break
            for ch in code:
                if ch == "{":
                    depth += 1
                    started = True
                elif ch == "}":
                    depth -= 1
            owner[j + 1] = name
            if started and depth == 0:
                break
            j += 1
        i = j + 1
    return owner


def function_in_header(lines, lineno):
    """Class::method for a line inside a class body of a header."""
    stack = []  # (class name, depth of its body)
    depth = 0
    for line in lines[:lineno - 1]:
        code = strip_code(line)
        m = CLASS.match(code)
        depth += code.count("{")
        if m and "{" in code:
            stack.append((m.group("name"), depth))
        depth -= code.count("}")
        while stack and depth < stack[-1][1]:
            stack.pop()
    cls = stack[-1][0] if stack else None
    m = METHOD.search(strip_code(lines[lineno - 1]))
    method = m.group("name") if m else "?"
    return f"{cls}::{method}" if cls else method


def locate(path, lineno, cache):
    if path not in cache:
        cache[path] = pathlib.Path(path).read_text().splitlines()
    lines = cache[path]
    if path.endswith(".h"):
        return function_in_header(lines, lineno)
    owners = cache.setdefault(path + "#owners", functions_of_source(lines))
    return owners.get(lineno, "?")


def rel(path):
    p = pathlib.Path(path)
    parts = p.parts
    return "/".join(parts[parts.index("src"):]) if "src" in parts else path


def read_findings(folder, cache):
    found = set()
    for tool, pattern, name in (("cppcheck", CPPCHECK, "cppcheck.txt"), ("clang-tidy", TIDY, "clang-tidy.txt")):
        for raw in (folder / name).read_text().splitlines():
            m = pattern.match(raw)
            if not m:
                continue
            path, lineno = m.group("file"), int(m.group("line"))
            func = locate(path, lineno, cache)
            source = cache[path][lineno - 1] if lineno <= len(cache[path]) else ""
            for check in m.group("check").split(","):
                found.add((tool, check, rel(path), func, m.group("msg"), lineno, source))
    return sorted(found, key=lambda f: (f[2], f[5], f[1]))


def read_backlog(path):
    rows = []
    for line in pathlib.Path(path).read_text().splitlines():
        if not line.startswith("| F-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        fid, tool, check, location, message, label = cells
        loc = re.findall(r"`([^`]+)`", location)
        note = NOTE.match(message)
        rows.append({"id": fid, "tool": tool, "check": check, "file": loc[0], "func": loc[1],
                     "msg": note.group("msg") if note else message, "note": note.group("note") if note else None,
                     "label": label})
    return rows


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    cache = {}
    findings = read_findings(pathlib.Path(sys.argv[1]), cache)
    rows = read_backlog(sys.argv[2])
    used = {}
    problems = 0
    print("| ID | Tool | Check | File › function | Line | Result |")
    print("| --- | --- | --- | --- | --- | --- |")
    for f in findings:
        tool, check, path, func, msg, lineno, source = f
        hits = [r for r in rows if (r["tool"], r["check"], r["file"], r["func"], r["msg"]) == (tool, check, path, func, msg)
                and (r["note"] is None or r["note"] in source)]
        if len(hits) == 1:
            used.setdefault(hits[0]["id"], []).append(lineno)
            print(f"| {hits[0]['id']} | {tool} | {check} | `{path}` › `{func}` | {lineno} | matches |")
        else:
            problems += 1
            print(f"| — | {tool} | {check} | `{path}` › `{func}` | {lineno} | NOT IN BACKLOG: {msg} |")
    for r in rows:
        n = len(used.get(r["id"], []))
        if n != 1:
            problems += 1
            print(f"| {r['id']} | {r['tool']} | {r['check']} | `{r['file']}` › `{r['func']}` | — | "
                  f"{'MISSING' if n == 0 else f'{n} findings'}: {r['msg']} |")
    print(f"\n{len(findings)} findings, {len(rows)} backlog rows, {problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
