#!/usr/bin/env python3
"""Check that the RB-1 knowledge is consistent: every citation points at a page and section that exist, every fact's
numbers are on the page it cites, the requirement, the push tests and the hazard log cite only facts and sections that
exist, and the PDF matches the Markdown (same pages, built from the current file).

Needs Python 3.9+ and PyYAML; the PDF check needs poppler-utils (pdftotext, pdfinfo). --no-pdf skips it.
Exit status: 0 all consistent, 1 a problem found, 2 usage error.
"""
import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML is required: pip install PyYAML==6.0.3", file=sys.stderr)
    sys.exit(2)

HERE = Path(__file__).resolve().parent.parent
NOTES = HERE / "rb1-robot-notes.md"
PDF = HERE / "rb1-robot-notes.pdf"
FACTS = HERE / "facts"
CITE = re.compile(r"\[RB1-NOTES p\.(\d+) §([\d.]+)\]")
TR_CITE = re.compile(r"\[TR §([\d.]+)\]")
FACT_REF = re.compile(r"fact: ([A-Z][A-Z0-9-]+)")
REQ_FACT = re.compile(r"`([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)`")
problems = []


def problem(msg):
    problems.append(msg)


def numbers(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from numbers(x)
    elif isinstance(v, list):
        for x in v:
            yield from numbers(x)
    elif isinstance(v, (int, float)) and not isinstance(v, bool):
        yield v


NUM = re.compile(r"0x[0-9A-Fa-f_]+|\d[\d,]*(?:\.\d+)?")


def page_numbers(text):
    """Every number written on a page, as a value: 115,200 and 0x0001_0000 included. Compared exactly, so a wrong
    value never matches a nearby one or a number that merely contains it."""
    out = set()
    for tok in NUM.findall(text):
        try:
            out.add(int(tok.replace("_", ""), 16) if tok.lower().startswith("0x") else float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def has_section(page, sec):
    """The section's own heading is on the page, not just a reference to it."""
    return f"**§{sec} " in page or f"## §{sec} " in page


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-pdf", action="store_true", help="skip the PDF check")
    args = ap.parse_args()

    notes = NOTES.read_text(encoding="utf-8")
    pages = notes.split("<!-- pagebreak -->")
    for i, page in enumerate(pages, 1):
        if f"page {i} of {len(pages)}" not in page:
            problem(f"RB1-NOTES page {i}: its footer does not say 'page {i} of {len(pages)}'")

    def cite_ok(where, p, sec):
        p = int(p)
        if not 1 <= p <= len(pages) or not has_section(pages[p - 1], sec):
            problem(f"{where}: [RB1-NOTES p.{p} §{sec}] — no such section on that page")
            return False
        return True

    requirement = (HERE / "requirement.md").read_text(encoding="utf-8")
    facts = {}
    for f in sorted(FACTS.glob("*.yaml")):
        for e in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("facts", []):
            if e["id"] in facts:
                problem(f"{f.name}: fact {e['id']} defined twice")
            if not isinstance(e, dict) or not {"id", "statement", "source"} <= e.keys():
                problem(f"{f.name}: an entry lacks id, statement or source: {e!r:.80}")
                continue
            facts[e["id"]] = e
            m = CITE.fullmatch(e["source"])
            if m:
                if not cite_ok(f"{f.name} {e['id']}", *m.groups()):
                    continue
                where, text = f"RB1-NOTES page {m.group(1)}", pages[int(m.group(1)) - 1]
            elif e["source"].startswith("REQ-RB1-007"):
                ac = re.search(r"AC-\d+", e["source"])
                rows = [l for l in requirement.splitlines() if ac and l.startswith(f"| {ac.group(0)} |")]
                where, text = e["source"], (rows[0] if rows else requirement)
                if ac and not rows:
                    problem(f"{f.name} {e['id']}: {ac.group(0)} is not in the requirement")
            else:
                problem(f"{f.name} {e['id']}: source {e['source']!r} is neither RB1-NOTES nor the requirement")
                continue
            on_page = page_numbers(text)
            for n in numbers(e.get("values", {})):
                if float(n) not in on_page:
                    problem(f"{f.name} {e['id']}: {n} is not in {where}")

    tr = (HERE / "team-rules.md").read_text(encoding="utf-8")
    texts = {name: (HERE / name).read_text(encoding="utf-8")
             for name in ("team-rules.md", "requirement.md", "hazard-log.md")}
    texts["rb1-robot-notes.md"] = notes
    texts["tests/push-tests.yaml"] = (HERE / "tests" / "push-tests.yaml").read_text(encoding="utf-8")
    tests = yaml.safe_load(texts["tests/push-tests.yaml"])
    ids = [pt["id"] for pt in tests.get("points", [])]
    if len(ids) != len(set(ids)) or not ids:
        problem("tests/push-tests.yaml: point IDs missing or not unique")
    for pt in tests.get("points", []):
        if not 0 < pt["fraction"] <= 1 or pt["direction"] not in ("front", "back"):
            problem(f"tests/push-tests.yaml {pt['id']}: fraction must be in (0, 1] and direction front or back")
    if not (tests.get("seeds") or {}).get("count"):
        problem("tests/push-tests.yaml: the seeds are not frozen")
    for key, val in (tests.get("pass") or {}).items():
        if not isinstance(val, dict) or val.get("fact") not in facts:
            problem(f"tests/push-tests.yaml pass.{key}: must name an existing fact")
    if not tests.get("pass"):
        problem("tests/push-tests.yaml: no pass thresholds")
    for name, text in texts.items():
        for p, sec in CITE.findall(text):
            cite_ok(name, p, sec)
        for sec in TR_CITE.findall(text):
            if f"**§{sec}**" not in tr and f"## §{sec} " not in tr:
                problem(f"{name}: [TR §{sec}] — no such section in the team rules")
    for ref in FACT_REF.findall(texts["tests/push-tests.yaml"]):
        if ref not in facts:
            problem(f"tests/push-tests.yaml: fact {ref} does not exist")
    for ref in REQ_FACT.findall(texts["requirement.md"]):
        if ref not in facts:
            problem(f"requirement.md: fact {ref} does not exist")

    if not args.no_pdf:
        check_pdf(notes, len(pages))

    for p in problems:
        print("✗", p)
    print(f"{len(pages)} pages, {len(facts)} facts, {len(problems)} problem(s)")
    return 1 if problems else 0


def check_pdf(notes, n_pages):
    if not PDF.exists():
        problem("rb1-robot-notes.pdf is missing: run tools/build-pdf.sh")
        return
    try:
        info = subprocess.run(["pdfinfo", str(PDF)], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"pdfinfo failed ({exc}); install poppler-utils or use --no-pdf", file=sys.stderr)
        sys.exit(2)
    sha8 = hashlib.sha256(NOTES.read_bytes()).hexdigest()[:8]
    if f"source {sha8}" not in info:
        problem(f"rb1-robot-notes.pdf was not built from the current Markdown (expected source {sha8})")
    got = int(re.search(r"^Pages:\s+(\d+)", info, re.M).group(1))
    if got != n_pages:
        problem(f"rb1-robot-notes.pdf has {got} pages, the Markdown {n_pages}")
        return
    for i in range(1, n_pages + 1):
        text = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", str(PDF), "-"],
                              capture_output=True, text=True, check=True).stdout
        if f"page {i} of {n_pages}" not in text:
            problem(f"rb1-robot-notes.pdf page {i} does not end with its own page footer")


if __name__ == "__main__":
    sys.exit(main())
