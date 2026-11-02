#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""checks/evidence-page.sh: one Markdown page for the batch, from the check results and the triage [TR §7.3-§7.4].

Every result carries its evidence tier; the page lists what emulation cannot show [CC1-PN §2.3], the allowed log
differences with their findings, and blocked requirements. With --agent-summary, an agent's claimed verdicts are
shown next to the checks' verdicts, and every disagreement is marked [TR §7.4]. Exit 0 when the page was written.
"""

import json
import pathlib
import re
import sys

import common as c

ORDER = ("build", "static", "unit", "size", "trace", "runtime-limits", "logdiff", "release")


def emulation_limits():
    text = (c.KNOWLEDGE_DIR / "cc1-platform-notes.md").read_text()
    m = re.search(r"\*\*§2\.3 What emulation cannot show\.\*\* (.*?)(?:\n- \*\*§|\n## )", text, re.S)
    return " ".join(m.group(1).split()) if m else "see CC1-PN §2.3"


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def page(results, triage, agent):
    got = {}
    for name in ORDER:
        p = results / f"{name}.json"
        if p.is_file():
            got[name] = json.loads(p.read_text())
    build = got.get("build", {})
    release = got.get("release")
    lines = [f"# Evidence page: {triage.get('batch', 'vstatd batch')}", ""]
    lines += [f"- Commit: `{build.get('commit', 'unknown')}`",
              f"- Build (SHA-256 of the stripped `vstatd`): `{build.get('details', {}).get('digest', 'none')}`",
              f"- Triage: base `{triage.get('base', '')[:12]}`, approved by {triage.get('approved', {}).get('by', '?')} "
              f"on {triage.get('approved', {}).get('at', '?')}",
              f"- Release check: **{release['verdict'] if release else 'not run'}**", ""]
    head = "| Check | Verdict | Evidence tier | Result |" + (" Agent said |" if agent else "")
    lines += [head, "| --- | --- | --- | --- |" + (" --- |" if agent else "")]
    for name in ORDER:
        if name not in got and name == "release":
            continue
        res = got.get(name, {})
        verdict = res.get("verdict", "missing")
        row = f"| `{name}` | **{verdict}** | {res.get('tier', '')} | {cell(res.get('summary', ''))} |"
        if agent:
            said = agent.get(name, "")
            row += f" {said}{' ⚠ disagrees' if said and said != verdict else ''} |"
        lines.append(row)
    lines.append("")

    findings = triage.get("findings", [])
    static = {f["id"]: f for f in got.get("static", {}).get("details", {}).get("findings", []) if f.get("id")}
    counts = {d: sum(1 for f in findings if f["decision"] == d) for d in ("fix", "justify", "defer")}
    lines += ["## Findings of the batch", "",
              f"{counts['fix']} fixed, {counts['justify']} justified, {counts['defer']} deferred.", "",
              "| Finding | Decision | Cites | Static analysis now |", "| --- | --- | --- | --- |"]
    for f in findings:
        cites = ", ".join(f.get("cites", []) + f.get("facts", [])) or (f.get("reason", "") if f["decision"] == "defer" else "")
        lines.append(f"| {f['id']} | {f['decision']} | {cell(cites)} | {static.get(f['id'], {}).get('status', '')} |")
    lines.append("")

    ld = got.get("logdiff", {}).get("details", {})
    if ld:
        lines += ["## Log comparison", "",
                  f"{ld.get('paired')} of {ld.get('baseline_entries')} baseline entries paired within "
                  f"{ld.get('window_ms')} ms; {ld.get('unexplained')} unexplained difference(s); "
                  f"{len(ld.get('allowed', []))} allowed.", ""]
        for a in ld.get("allowed", []):
            lines.append(f"- Allowed ({a['finding']}), only in the {a['side']}: `{json.dumps(a['entry'])}`")
        for a in ld.get("allowed_not_seen", []):
            lines.append(f"- Allowed by the triage ({a['finding']}) but not seen: `{json.dumps(a['entry'])}`")
        lines.append("")
    rl = got.get("runtime-limits", {}).get("details", {})
    if rl:
        lines += ["## Runtime figures", "",
                  f"Peak RSS {rl.get('vm_hwm_kib')} KiB (limit {rl.get('peak_rss_limit_kib')}, baseline "
                  f"{rl.get('baseline_vm_hwm_kib')}); {rl.get('threads_at_end')} threads at the end (limit "
                  f"{rl.get('threads_limit')}); CPU time x{rl.get('cpu_relative_to_baseline')} of the baseline, "
                  f"reported only. Tier: {got['runtime-limits'].get('tier')}.", ""]
    tiers = {res.get("tier") for res in got.values()}
    if "emulation" in tiers:
        lines += ["## What emulation cannot show", "", emulation_limits(), ""]
    if release:
        rd = release.get("details", {})
        if rd.get("blocked_requirements"):
            lines += ["## Blocked by evidence tier", ""] + [f"- {i}" for i in rd["blocked_requirements"]] + [""]
        if rd.get("repair_rounds"):
            lines += ["## Bounded repair", "", f"Rounds used: `{json.dumps(rd['repair_rounds'])}`; limits "
                      f"`{json.dumps(rd['repair_limits'])}` (TR §5.1).", ""]
        if release.get("reasons"):
            lines += ["## Why the release check did not pass", ""] + [f"- {cell(x)}" for x in release["reasons"]] + [""]
    lines += ["## Sign-off", "", "Release owner: ____________________  Date: ____________",
              "", "Decision: ☐ sign off  ☐ return to the batch", ""]
    return "\n".join(lines)


def main():
    p = c.Parser(prog="checks/evidence-page.sh")
    p.add_argument("--results", default="results")
    p.add_argument("--triage", required=True)
    p.add_argument("--out", default=None, help="default: <results>/evidence.md")
    p.add_argument("--agent-summary", default=None, help="JSON {check: verdict the agent reported}")
    try:
        args = p.parse_args()
    except c.Usage as e:
        print(f"evidence-page: usage error: {e}", file=sys.stderr)
        return 2
    results = pathlib.Path(args.results)
    try:
        triage = json.loads(pathlib.Path(args.triage).read_text())
        agent = json.loads(pathlib.Path(args.agent_summary).read_text()) if args.agent_summary else None
    except (OSError, ValueError) as e:
        print(f"evidence-page: {e}", file=sys.stderr)
        return 2
    out = pathlib.Path(args.out or results / "evidence.md")
    out.write_text(page(results, triage, agent))
    print(f"evidence page: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
