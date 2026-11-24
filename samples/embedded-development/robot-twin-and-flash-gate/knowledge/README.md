# Knowledge for the robot scenario

Everything the agents need to know about RB-1, with citations. All of it is synthetic and written for this sample:
RB-1 describes no real robot, supplier or product.

| File | What it is | Cite as |
| --- | --- | --- |
| [`rb1-robot-notes.md`](rb1-robot-notes.md) and [`rb1-robot-notes.pdf`](rb1-robot-notes.pdf) | RB1-NOTES rev 1.0: mechanics, motors and IMU, the controller firmware, its serial interface, the flash layout and images, the safe operating conditions, the evidence tiers. 8 pages; the PDF has the same page breaks | `[RB1-NOTES p.4 §3.3]` |
| [`team-rules.md`](team-rules.md) | Firmware rules, both builds, resource limits, requirements and frozen tests, bounded repair, physical actions, definition of done | `[TR §4.2]` |
| [`hazard-log.md`](hazard-log.md) | The hazards of a firmware change, each with its measure and the check or gate that verifies it | `HL-4` |
| [`requirement.md`](requirement.md) | The change request REQ-RB1-007, a recovery limit in the actuator guard, with its acceptance criteria | `REQ-RB1-007 AC-2` |
| [`tests/push-tests.yaml`](tests/push-tests.yaml) | The frozen push tests: points, seeds, pass thresholds, each pass threshold a fact entry | `PT-05` |
| [`facts/`](facts/) | Fact entries extracted from RB1-NOTES and the requirement: 25 parameters (`parameters.yaml`) and 19 rules and limits (`rules.yaml`), each with its page and section | the entry's `source` |

Two values are *to be set*: the rated push impulse (`PUSH-RATED`) and the confirmation of the travel limit
(`TRAVEL-LIMIT`). They are frozen, with the push tests, after the twin's sweep of build plan item 3 and before any
firmware change is written ([TR §4.2](team-rules.md)).

## How the agents use it

- In Kiro the Markdown files are steering files; in Kiro Crew the folder is a knowledge source the agents search.
- Every requirement, test, twin parameter and limit in `src/limits.h` cites a fact entry; `checks/trace.sh` enforces
  it. The twin reads its parameters from the fact entries, not from numbers of its own.
- The notes describe the robot as it is. A change that would alter behaviour they describe needs a change to the
  notes first.

## Keep it consistent

```bash
pip install PyYAML==6.0.3
python3 tools/check_knowledge.py            # needs poppler-utils (pdftotext, pdfinfo); --no-pdf skips the PDF
tools/build-pdf.sh                          # after editing rb1-robot-notes.md; see the script for what it needs
```

`check_knowledge.py` fails when a citation points at a page without that section, when a fact's numbers are not on the
page or the acceptance criterion it cites (numbers are compared as values, never rounded, so 0.31 does not match 0.315;
a value equal to another number on the same page or row still passes), when the requirement or the push tests use a fact
that does not exist, when the hazard log or the requirement cites a team-rule section that does not exist, or when the
PDF was built from an older Markdown file or its pages no longer match.

## Third-party references

| Reference | Used for | Licence | In this repository |
| --- | --- | --- | --- |
| [PyYAML](https://github.com/yaml/pyyaml) | Reading the facts and the push tests | MIT | Not included; installed with pip |
| [pandoc](https://pandoc.org/) | Rendering the PDF | GPL-2.0-or-later | Not included; used as a tool |
| [Chromium](https://www.chromium.org/), or Google Chrome | Printing the PDF | BSD-3-Clause (Chromium); Google Chrome is proprietary (Google Chrome Terms of Service) | Not included; used as a tool |
| [Liberation Sans](https://github.com/liberationfonts/liberation-fonts) and [DejaVu Sans Mono](https://dejavu-fonts.github.io/) | Fonts of the PDF | OFL-1.1; Bitstream Vera licence | Subsets embedded in `rb1-robot-notes.pdf` |
| [Poppler](https://poppler.freedesktop.org/) `pdftotext`, `pdfinfo` | Reading the PDF in the check | GPL-2.0-only or GPL-3.0-only (parts GPL-2.0-or-later) | Not included; used as a tool |
