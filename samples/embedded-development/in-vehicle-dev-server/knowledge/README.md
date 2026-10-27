# Knowledge for the in-vehicle scenario

Everything the agents need to know about `vstatd` and CC-1, with citations. All of it is synthetic and written for
this sample.

| File | What it is | Cite as |
| --- | --- | --- |
| [`vstatd-interface.md`](vstatd-interface.md) and [`vstatd-interface.pdf`](vstatd-interface.pdf) | The interface specification VSTATD-IF rev 1.3: gateway records, signals, decoding, supervision, IPC, errors, runtime log, start-up. 11 pages; the PDF has the same page breaks | `[VSTATD-IF p.7 §4.1]` |
| [`cc1-gateway.dbc`](cc1-gateway.dbc) | The CAN database: 9 messages, 24 signals, cycle times (`GenMsgCycleTime`) and SNA values (`SnaRaw`) | `[VSTATD-IF p.4–5 §3.1]` |
| [`vss-mapping.yaml`](vss-mapping.yaml) | Each published signal path (a COVESA VSS v6.1 name) and the CAN signal it is decoded from | `[VSTATD-IF p.4–5 §3.1]` |
| [`cc1-platform-notes.md`](cc1-platform-notes.md) | The target, the emulated CC-1, resource limits, start-up order, log format, log comparison settings, toolchain, bench states and runs | `[CC1-PN §6.3]` |
| [`team-rules.md`](team-rules.md) | C++ rules, build flags, analyser settings, triage policy, repair bounds, definition of done | `[TR §4.1]` |
| [`findings-backlog.md`](findings-backlog.md) | 30 static analysis findings on the current release; 22 labelled `fix` for this batch | `F-001` … `F-030` |
| [`facts/`](facts/) | Fact entries extracted from VSTATD-IF: one per signal (`signals.yaml`), per message (`messages.yaml`) and per rule (`rules.yaml`), each with its page and section | the entry's `source` |

## How the agents use it

- In Kiro the Markdown files are steering files and the agents open the others as files; in Kiro Crew the folder is
  a knowledge source the agents search. See
  [Where it runs](../README.md#where-it-runs).
- Every triage decision, change and justification cites a finding and, where it touches behaviour, a fact entry or a
  page of VSTATD-IF. `checks/trace.sh` enforces it.
- The specification describes the current behaviour, which the batch must keep ([TR §4.2](team-rules.md)). A change
  that would alter it needs a specification change first.

## Keep it consistent

```bash
pip install cantools==45.1.0 PyYAML==6.0.3   # or use the build server container
python3 tools/check_knowledge.py             # needs poppler-utils (pdftotext, pdfinfo); --no-pdf skips the PDF
tools/build-pdf.sh                           # after editing vstatd-interface.md; see the script for what it needs
```

`check_knowledge.py` fails when a citation points at a page without that section or at a section that does not
exist, when a fact's numbers are not on the page it cites, when the PDF was built from an older Markdown file or its
pages no longer match the specification's, when the DBC, the facts, the mapping and the specification tables
disagree, or when a backlog finding uses a clang-tidy check that the team rules do not enable. To also
check every signal path, data type and unit against the VSS release, export it with the
[vss-tools](https://github.com/COVESA/vss-tools) and pass the file:

```bash
git clone --depth 1 --branch v6.1 https://github.com/COVESA/vehicle_signal_specification.git /tmp/vss
pip install vss-tools==6.1.0
vspec export csv -s /tmp/vss/spec/VehicleSignalSpecification.vspec -u /tmp/vss/spec/units.yaml \
  -q /tmp/vss/spec/quantities.yaml -o /tmp/vss.csv
python3 tools/check_knowledge.py --vss-csv /tmp/vss.csv
```

## Third-party references

| Reference | Used for | Licence | In this repository |
| --- | --- | --- | --- |
| [COVESA Vehicle Signal Specification](https://github.com/COVESA/vehicle_signal_specification), release v6.1 | Signal path names, data types and units | MPL-2.0 | Names only; no VSS files are copied |
| DBC, the CAN database format introduced by Vector Informatik | File format of `cc1-gateway.dbc` | Format, no licence attached | `cc1-gateway.dbc` was written for this sample |
| [cantools](https://github.com/cantools/cantools) | Parsing the DBC in `check_knowledge.py` | MIT | Not included; installed with pip |
| [PyYAML](https://github.com/yaml/pyyaml) | Reading the facts and the mapping | MIT | Not included; installed with pip |
| [vss-tools](https://github.com/COVESA/vss-tools) | Optional export of a VSS release for the check | MPL-2.0 | Not included; installed with pip |
| [pandoc](https://pandoc.org/) | Rendering the PDF | GPL-2.0-or-later | Not included; used as a tool |
| [Chromium](https://www.chromium.org/), or Google Chrome | Printing the PDF | BSD-3-Clause (Chromium); Google Chrome is proprietary (Google Chrome Terms of Service) | Not included; used as a tool |
| [Liberation Sans](https://github.com/liberationfonts/liberation-fonts) and [DejaVu Sans Mono](https://dejavu-fonts.github.io/) | Fonts of the PDF | OFL-1.1; Bitstream Vera licence | Subsets embedded in `vstatd-interface.pdf` |
| [Poppler](https://poppler.freedesktop.org/) `pdftotext`, `pdfinfo` | Reading the PDF in the check | GPL-2.0-only or GPL-3.0-only (parts GPL-2.0-or-later) | Not included; used as a tool |
