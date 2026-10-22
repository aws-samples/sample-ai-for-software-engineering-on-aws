# Reference project: embedded development

A small firmware project to practice the sample on, without hardware.

Planned contents:

- firmware in C for an Arm Cortex-M board that QEMU emulates, built with the Arm GNU Toolchain and CMake;
- host unit tests, and simulation tests that boot the image in QEMU and check its console output;
- knowledge for the emulated board, so the agents have hardware facts to cite from the start;
- a backlog of features to try, such as a new console command, a debounced input driver and a watchdog;
- a hardware profile that points the same flow at a real board and bench.
