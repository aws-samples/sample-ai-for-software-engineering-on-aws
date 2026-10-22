# Knowledge: embedded development

What the agents look up and cite before they write anything.

Planned contents:

- **Hardware facts** extracted from datasheets, reference manuals and schematics into Markdown, one fact per entry
  with its source document and page: registers and their fields, pin assignments, clock and timing constraints,
  electrical limits;
- a short guide and prompts for doing that extraction on a team's own documents, with a cross-check step so that
  every extracted value is compared with its page;
- the team's **coding standard** for C on the target;
- **toolchain conventions**: compiler and flags, build system, flashing and debugging tools;
- **safety limits** that the physical gate enforces, such as minimum battery level, supply voltage range and maximum
  temperature.

The reference project ships knowledge for its emulated board, so the sample works before a team adds its own.
