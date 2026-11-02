#!/usr/bin/env python3
"""Check that the knowledge files agree with each other.

- The specification: page markers, page footers and the sections defined on each page.
- The rendered PDF: built from the current Markdown, one page per specification page (needs poppler-utils).
- Citations: every [VSTATD-IF p.N §x.y] in the facts, the knowledge and the rehearsal notes points at a page that
  defines that section; every [CC1-PN §x] and [TR §x] names a section that exists. Numbers in a fact's values appear
  on the page it cites.
- The CAN database (parsed with cantools) against the signal and message facts, the specification tables and the
  VSS mapping, including value tables and allowed values.
- Optionally the VSS mapping against a VSS release exported to CSV with vss-tools.
- The findings backlog: unique IDs, known labels, and clang-tidy checks that the team rules enable.

Usage: check_knowledge.py [--vss-csv vss.csv] [--no-pdf]
Requires: Python 3.9+, PyYAML, cantools; pdftotext and pdfinfo (poppler-utils) unless --no-pdf.
Exit status 0 when every check passes, 1 otherwise.
"""
import argparse
import csv
import fnmatch
import hashlib
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import cantools
import yaml

HERE = Path(__file__).resolve().parent.parent
SPEC = HERE / "vstatd-interface.md"
PDF = HERE / "vstatd-interface.pdf"
DBC = HERE / "cc1-gateway.dbc"
MAPPING = HERE / "vss-mapping.yaml"
FACTS = HERE / "facts"
BACKLOG = HERE / "findings-backlog.md"
PN = HERE / "cc1-platform-notes.md"
TR = HERE / "team-rules.md"
NOTES = [*HERE.glob("*.md"), *(HERE.parent / "rehearsal").glob("*.md")]

CITE = re.compile(r"\[VSTATD-IF p\.(\d+)(?:[–-](\d+))? §(\d+(?:\.\d+)?)\]")
OTHER_CITE = re.compile(r"\[(CC1-PN|TR) §(\d+(?:\.\d+)?)\]")
FOOTER = re.compile(r"page (\d+) of (\d+)")
DEFINED = re.compile(r"(?:^## |\*\*)§(\d+(?:\.\d+)?)", re.M)

errors = []


def fail(msg):
    errors.append(msg)


def flat(text):
    """Page text with digit-group spaces and typographic minus removed, for finding numbers."""
    return re.sub(r"(?<=\d)[ \u2009\u202f](?=\d{3}\b)", "", text).replace("\u2212", "-")


def spec_pages():
    pages = SPEC.read_text(encoding="utf-8").split("\n<!-- pagebreak -->\n")
    total = len(pages)
    sections = {}
    for n, text in enumerate(pages, start=1):
        footers = FOOTER.findall(text)
        if footers != [(str(n), str(total))]:
            fail(f"spec page {n}: footer should read 'page {n} of {total}', found {footers}")
        sections[n] = set(DEFINED.findall(text))
    return pages, sections


def check_pdf(total):
    missing = [t for t in ("pdftotext", "pdfinfo") if not shutil.which(t)]
    if missing:
        fail(f"{' and '.join(missing)} not found: install poppler-utils, or run with --no-pdf")
        return
    info = subprocess.run(["pdfinfo", str(PDF)], capture_output=True, text=True).stdout
    sha8 = hashlib.sha256(SPEC.read_bytes()).hexdigest()[:8]
    if f"(source {sha8})" not in info:
        fail(f"PDF was not built from the current vstatd-interface.md (source {sha8}); run tools/build-pdf.sh")
    m = re.search(r"^Pages:\s+(\d+)", info, re.M)
    if not m or int(m.group(1)) != total:
        found = m.group(1) if m else "?"
        fail(f"PDF has {found} pages, the specification has {total}; rebuild with tools/build-pdf.sh")
        return
    for n in range(1, total + 1):
        text = subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), str(PDF), "-"],
                              capture_output=True, text=True).stdout
        if FOOTER.findall(text) != [(str(n), str(total))]:
            fail(f"PDF page {n} does not end the specification's page {n}: a page overflowed")


def cited_pages(where, cite, sections):
    """Return the cited page numbers, or None after reporting a bad citation."""
    m = CITE.fullmatch(cite)
    if not m:
        fail(f"{where}: citation '{cite}' is not in the form [VSTATD-IF p.N §x.y]")
        return None
    first, last, sec = int(m.group(1)), int(m.group(2) or m.group(1)), m.group(3)
    pages = list(range(first, last + 1))
    if any(p not in sections for p in pages):
        fail(f"{where}: cites page {first}-{last}, the specification has {len(sections)} pages")
        return None
    if not any(sec in sections[p] for p in pages):
        fail(f"{where}: §{sec} is not on page {first}" + (f"-{last}" if last != first else ""))
        return None
    return pages


def same(a, b):
    return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)


def num(x):
    x = float(x)
    return str(int(x)) if x.is_integer() else repr(x)


def table_rows(page_text):
    rows = {}
    for line in page_text.splitlines():
        if line.startswith("| `Vehicle."):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows[cells[0].strip("`")] = cells
    return rows


def check_signals(signals, messages, pages, sections, db, mapping):
    dbc_msgs = {m.name: m for m in db.messages}
    for f in messages:
        m = dbc_msgs.get(f["message"])
        if not m:
            fail(f"facts {f['id']}: message not in the DBC")
            continue
        if f"0x{m.frame_id:03X}" != f["can_id"]:
            fail(f"facts {f['id']}: CAN ID {f['can_id']}, DBC 0x{m.frame_id:03X}")
        if m.cycle_time != f["cycle_ms"]:
            fail(f"facts {f['id']}: cycle {f['cycle_ms']} ms, DBC {m.cycle_time} ms")
        if m.senders != [f["sender"]]:
            fail(f"facts {f['id']}: sender {f['sender']}, DBC {m.senders}")
        if f["timeout_ms"] != 3 * f["cycle_ms"]:
            fail(f"facts {f['id']}: timeout is not 3 x cycle")
        row = f"| {f['can_id']} | {f['message']} | {f['sender']} | {f['cycle_ms']} ms | {f['timeout_ms']} ms |"
        if row not in pages[4]:
            fail(f"facts {f['id']}: row not found in the message table on page 5")
    if set(dbc_msgs) != {f["message"] for f in messages}:
        fail("messages in the DBC and in facts/messages.yaml differ")

    seen = set()
    for f in signals:
        m = dbc_msgs.get(f["message"])
        s = next((s for s in m.signals if s.name == f["signal"]), None) if m else None
        if not s:
            fail(f"facts {f['id']}: signal not in the DBC")
            continue
        seen.add((m.name, s.name))
        for name, dbc_v, fact_v in [("start_bit", s.start, f["start_bit"]), ("length", s.length, f["length"]),
                                    ("signed", s.is_signed, f["signed"]), ("unit", s.unit or None, f["unit"])]:
            if dbc_v != fact_v:
                fail(f"facts {f['id']}: {name} {fact_v}, DBC {dbc_v}")
        for name, dbc_v, fact_v in [("factor", s.scale, f["factor"]), ("offset", s.offset, f["offset"]),
                                    ("valid_min", s.minimum, f["valid_min"]),
                                    ("valid_max", s.maximum, f["valid_max"])]:
            if not same(dbc_v, fact_v):
                fail(f"facts {f['id']}: {name} {fact_v}, DBC {dbc_v}")
        if s.byte_order != "little_endian":
            fail(f"facts {f['id']}: DBC signal is not little-endian ({s.byte_order})")
        sna = s.dbc.attributes.get("SnaRaw") if s.dbc else None
        if sna is None or sna.value != f["sna_raw"]:
            fail(f"facts {f['id']}: SNA raw {f['sna_raw']}, DBC {sna.value if sna else 'missing'}")
        if f["timeout_ms"] != 3 * m.cycle_time:
            fail(f"facts {f['id']}: timeout {f['timeout_ms']} ms, 3 x DBC cycle is {3 * m.cycle_time} ms")
        if (s.comment or "") != f"VSS {f['path']}":
            fail(f"facts {f['id']}: DBC comment should be 'VSS {f['path']}'")
        if f["length"] > 24:
            fail(f"facts {f['id']}: raw longer than 24 bits contradicts §3.3")
        if f["log_deadband"] != "any change" and f["log_deadband_raw"] != round(f["log_deadband"] / f["factor"]):
            fail(f"facts {f['id']}: log_deadband_raw is not the deadband divided by the factor")
        choices = {int(k): str(v) for k, v in (s.choices or {}).items()}

        e = mapping["signals"].get(f["path"])
        if not e or (e["dbc_message"], e["dbc_signal"]) != (f["message"], f["signal"]):
            fail(f"facts {f['id']}: VSS mapping for {f['path']} does not point at {f['message']}.{f['signal']}")
        else:
            for key in ("vss_type", "vss_datatype", "log_deadband", "log_deadband_raw"):
                if e.get(key) != f.get(key):
                    fail(f"facts {f['id']}: {key} differs between mapping ({e.get(key)}) and facts ({f.get(key)})")
            if e.get("vss_unit") != f["vss_unit"]:
                fail(f"facts {f['id']}: vss_unit differs between mapping and facts")
            for raw, value in (e.get("map") or {}).items():
                want = str(value).lower() if isinstance(value, bool) else str(value)
                if choices.get(int(raw)) != want:
                    fail(f"facts {f['id']}: mapping {raw} -> {value}, DBC value table says {choices.get(int(raw))}")
            if "allowed_raw" in e or "allowed_raw" in f:
                if e.get("allowed_raw") != f.get("allowed_raw"):
                    fail(f"facts {f['id']}: allowed_raw differs between mapping and facts")
                if set(f.get("allowed_raw") or []) != set(choices) - {f["sna_raw"]}:
                    fail(f"facts {f['id']}: allowed_raw does not match the DBC value table")

        pages_cited = cited_pages(f"facts {f['id']}", f["source"], sections)
        if not pages_cited:
            continue
        cells = table_rows(pages[pages_cited[0] - 1]).get(f["path"])
        if not cells:
            fail(f"facts {f['id']}: no row for {f['path']} in the signal table on page {pages_cited[0]}")
            continue
        _, can_sig, to_phys, valid, sna_cell, deadband = cells
        if can_sig != f"{f['can_id']} {f['message']}.{f['signal']}":
            fail(f"facts {f['id']}: table says {can_sig}")
        if flat(sna_cell) != str(f["sna_raw"]):
            fail(f"facts {f['id']}: table SNA {sna_cell}, fact {f['sna_raw']}")
        if f"{f['length']} bit" not in to_phys:
            fail(f"facts {f['id']}: table length differs ({to_phys})")
        if f["factor"] != 1 and f"× {num(f['factor'])}" not in to_phys:
            fail(f"facts {f['id']}: table factor differs ({to_phys})")
        if f["offset"] and f"{num(abs(f['offset']))}" not in to_phys:
            fail(f"facts {f['id']}: table offset differs ({to_phys})")
        if valid.startswith(("false", "raw", "−1, 0")):
            pass  # flags and enumerations: checked through the value tables above
        elif not (flat(valid).startswith(f"{num(f['valid_min'])} to {num(f['valid_max'])}")):
            fail(f"facts {f['id']}: table valid range '{valid}', fact {f['valid_min']} to {f['valid_max']}")
        expect_db = "any change" if f["log_deadband"] == "any change" else f"(raw {f['log_deadband_raw']})"
        if expect_db not in deadband:
            fail(f"facts {f['id']}: table deadband '{deadband}', fact {f['log_deadband']} raw {f['log_deadband_raw']}")

    for missing in sorted({(m.name, s.name) for m in db.messages for s in m.signals} - seen):
        fail(f"DBC signal {missing[0]}.{missing[1]} has no fact entry")
    if set(mapping["signals"]) != {f["path"] for f in signals}:
        fail("paths in vss-mapping.yaml and facts/signals.yaml differ")
    return sum(len(m.signals) for m in db.messages)


def check_citations(rules, pages, sections):
    for f in rules:
        cited = cited_pages(f"facts {f['id']}", f["source"], sections)
        if not cited:
            continue
        text = flat("\n".join(pages[p - 1] for p in cited))
        for key, value in (f.get("values") or {}).items():
            if not re.search(rf"(?<![\d.]){re.escape(str(value))}(?![\d])", text):
                fail(f"facts {f['id']}: {key}={value} does not appear on the cited page")
    other = {"CC1-PN": set(DEFINED.findall(PN.read_text(encoding="utf-8"))),
             "TR": set(DEFINED.findall(TR.read_text(encoding="utf-8")))}
    for path in NOTES:
        text = path.read_text(encoding="utf-8")
        for m in CITE.finditer(text):
            cited_pages(path.name, m.group(0), sections)
        for doc, sec in OTHER_CITE.findall(text):
            if sec not in other[doc] and not any(s.startswith(sec + ".") for s in other[doc]):
                fail(f"{path.name}: [{doc} §{sec}] does not exist")


def check_vss(path_csv, mapping):
    rows = {r["Signal"]: r for r in csv.DictReader(open(path_csv, encoding="utf-8"))}
    for path, e in mapping["signals"].items():
        r = rows.get(path)
        if not r:
            fail(f"VSS: {path} is not in {path_csv}")
            continue
        got = (r["Type"], r["DataType"], r["Unit"] or None)
        want = (e["vss_type"], e["vss_datatype"], e.get("vss_unit"))
        if got != want:
            fail(f"VSS: {path} is {got}, mapping says {want}")
        if r.get("Deprecated"):
            fail(f"VSS: {path} is deprecated: {r['Deprecated']}")
        allowed = r.get("Allowed") or ""
        for value in (e.get("map") or {}).values():
            if isinstance(value, str) and f"'{value}'" not in allowed:
                fail(f"VSS: {path} does not allow '{value}'")


def check_backlog():
    rows = [l for l in BACKLOG.read_text(encoding="utf-8").splitlines() if l.startswith("| F-")]
    ids = [r.split("|")[1].strip() for r in rows]
    if len(ids) != len(set(ids)):
        fail("backlog: duplicate finding IDs")
    tr31 = re.search(r"\*\*§3\.1\*\*(.*?)(?=\n- \*\*§)", TR.read_text(encoding="utf-8"), re.S)
    globs = re.findall(r"`([a-z]+(?:-[a-z0-9]+)*-?\*?|[a-z]+-\*)`", tr31.group(1)) if tr31 else []
    labels = {"fix": 0, "later": 0}
    for r in rows:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        fid, tool, check, label = cells[0], cells[1], cells[2], cells[-1]
        if label not in labels:
            fail(f"backlog: {fid} has label '{label}'")
        else:
            labels[label] += 1
        if tool == "clang-tidy" and not any(fnmatch.fnmatch(check, g) for g in globs):
            fail(f"backlog: {fid} uses {check}, which TR §3.1 does not enable")
        if tool not in ("cppcheck", "clang-tidy"):
            fail(f"backlog: {fid} has tool '{tool}'")
    return len(ids), labels


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vss-csv", help="VSS release exported with: vspec export csv ... (checks paths, types, units)")
    ap.add_argument("--no-pdf", action="store_true", help="skip the PDF check")
    args = ap.parse_args()

    pages, sections = spec_pages()
    if not args.no_pdf:
        check_pdf(len(pages))

    signals = yaml.safe_load((FACTS / "signals.yaml").read_text(encoding="utf-8"))["signals"]
    messages = yaml.safe_load((FACTS / "messages.yaml").read_text(encoding="utf-8"))["messages"]
    rules = yaml.safe_load((FACTS / "rules.yaml").read_text(encoding="utf-8"))["rules"]
    ids = [f["id"] for f in signals + messages + rules]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        fail(f"facts: duplicate id {dup}")
    for f in messages:
        cited_pages(f"facts {f['id']}", f["source"], sections)
    check_citations(rules, pages, sections)

    db = cantools.database.load_file(str(DBC))
    mapping = yaml.safe_load(MAPPING.read_text(encoding="utf-8"))
    n_dbc = check_signals(signals, messages, pages, sections, db, mapping)
    if args.vss_csv:
        check_vss(args.vss_csv, mapping)
    n_findings, labels = check_backlog()

    if errors:
        print("\n".join(f"FAIL {e}" for e in errors))
        print(f"{len(errors)} problem(s)")
        return 1
    print(f"PASS {len(pages)} specification pages, {len(ids)} facts ({len(signals)} signals, {len(messages)} "
          f"messages, {len(rules)} rules), {n_dbc} DBC signals, {n_findings} findings ({labels['fix']} fix, "
          f"{labels['later']} later)" + (", VSS checked" if args.vss_csv else "")
          + ("" if args.no_pdf else ", PDF current and pages match"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
