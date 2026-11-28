# RB1-NOTES: RB-1 robot notes

| | |
| --- | --- |
| Document | RB1-NOTES, revision 1.0 |
| Product | RB-1, a two-wheeled self-balancing robot with a controller board and a main computer |
| Status | Released; the rated push impulse (§6.5) is *to be set* after the twin's sweep |
| Related | Team rules (TR), hazard log (HL), the change request REQ-RB1-007, the push tests `tests/push-tests.yaml` |

> All names, values and behaviour in this document are synthetic and were written for the AI-DLC embedded sample.
> They describe no real robot, supplier or product.

## §0 About this document

**§0.1 Scope.** This document describes RB-1 as far as a change to its controller firmware or its main computer's
software needs it: the mechanics, the motors and the inertial measurement unit (IMU), the controller's interface, the
safe operating limits, the flash layout and the conditions under which the robot may be flashed, moved or updated. A
change that alters behaviour described here needs an approved document change first.

**§0.2 How to cite.** Cite this document as `[RB1-NOTES p.<page> §<section>]`, for example `[RB1-NOTES p.4 §3.3]`.
Each page ends with its page number; the rendered PDF has the same page breaks.

**§0.3 Normative words.** *Shall* is a requirement. *Should* is a recommendation that a change may depart from only
with a recorded reason. *May* is a permission.

**§0.4 Units and signs.** SI units. Tilt is the body's pitch angle, positive when the top leans forward. Wheel speed
is positive forward. Travel is the distance the axle has moved along the floor since a reference point, positive
forward.

**§0.5 Revision history.**

| Revision | Change |
| --- | --- |
| 1.0 | First release |

RB1-NOTES rev 1.0 · page 1 of 8

<!-- pagebreak -->

## §1 The robot

**§1.1 Two computers.** RB-1 has a *controller*, a Cortex-M3 microcontroller without a floating-point unit that runs
the balance firmware, and a *main computer*, an embedded Linux system that runs the robot app and the update client.
They are connected by a serial link (§4). The controller keeps the robot upright and safe whatever the main computer
does; the main computer never drives the motors directly.

**§1.2 Geometry and mass.**

| Quantity | Value |
| --- | --- |
| Total mass | 1.60 kg |
| Body mass (without wheels) | 1.40 kg |
| Mass of each wheel with its tyre | 0.10 kg |
| Wheel radius | 0.040 m |
| Track width (wheel centre to wheel centre) | 0.140 m |
| Height of the body's centre of mass above the wheel axle | 0.090 m |
| Body moment of inertia about the axle (pitch), its own inertia included | 0.0147 kg·m² |
| Height of the top of the body above the floor | 0.200 m |

**§1.3 The body as an inverted pendulum.** With the values of §1.2 and no motor torque, the tilt grows with a time
constant of about 66 ms (about 110 ms if the axle were held). The controller's loop period (§3.1) is chosen well below
it.

**§1.4 The stand.** RB-1 rests on a rear stand when it is not balancing. On the stand it leans back by 30° to 35° and
its wheels are off the floor. The controller reports `on_stand` from the tilt and the wheel load (§4.3).

RB1-NOTES rev 1.0 · page 2 of 8

<!-- pagebreak -->

## §2 Motors, encoders and the IMU

**§2.1 Motors.** Each wheel is driven by a geared DC motor with an encoder, through an H-bridge driver commanded by
pulse-width modulation (PWM).

| Quantity | Value |
| --- | --- |
| Battery | 7.4 V nominal (6.6 V empty, 8.4 V full) |
| Stall torque at the wheel, each wheel, at 7.4 V | 0.45 N·m |
| No-load speed at the wheel, at 7.4 V | 300 rpm (1.26 m/s at the tyre) |
| Encoder resolution at the wheel | 1,320 counts per revolution |
| PWM frequency | 20 kHz |
| Driver dead time | 1 µs |

**§2.2 Torque and speed.** At a given voltage the torque a motor can give falls linearly with its speed. At 7.4 V each
wheel gives 0.45 N·m at standstill and none at 1.26 m/s, so the guard's torque limit (§3.3) is available only up to
0.38 m/s, and at 0.80 m/s a wheel gives at most 0.16 N·m.

**§2.3 IMU.** A six-axis IMU (accelerometer and gyroscope) is mounted on the body 0.050 m above the axle.

| Quantity | Value |
| --- | --- |
| Gyroscope range and scale | ±2000 °/s, 16.4 LSB per °/s |
| Accelerometer range and scale | ±8 g, 4096 LSB per g |
| Output data rate | 1,000 Hz |
| Gyroscope noise density | 0.007 °/s/√Hz |
| Gyroscope bias at power-on | within ±0.5 °/s |
| Accelerometer noise density | 150 µg/√Hz |

**§2.4 Calibration.** The IMU's mounting offsets and the angle at which the body balances are measured for each robot
and kept in its calibration data (§5.2). This document gives no values for them.

RB1-NOTES rev 1.0 · page 3 of 8

<!-- pagebreak -->

## §3 The controller firmware

**§3.1 Loop.** The balance loop runs every 5 ms (200 Hz), started by a timer interrupt. Each cycle reads the IMU,
estimates the tilt, runs the balance controller, applies the actuator guard and writes the PWM.

**§3.2 Arithmetic.** The controller has no floating-point unit. The firmware uses fixed-point arithmetic: angles in
Q16.16 degrees, rates and speeds in Q16.16 per second, and Q1.15 for the controller's gains.

**§3.3 Actuator guard.** After the balance controller and before the PWM, the actuator guard limits what the firmware
commands:

| Limit | Value |
| --- | --- |
| Commanded wheel speed | 0.80 m/s at the tyre |
| Commanded torque per wheel | 70 % of the stall torque of §2.1 (0.315 N·m) |
| Turn rate commanded by the main computer | 180 °/s |

The guard limits what is commanded; a push can still make the wheels turn faster for a moment. A limit reached is
reported in the telemetry flags (§4.3).

**§3.4 Fall stop.** When the tilt stays beyond ±60° for 0.3 s, the firmware stops both motors and reports `fallen`.
It does not restart them until the robot has been on its stand and stood up again.

**§3.5 Memory.** The application image shall fit in 184 KiB of flash and 64 KiB of RAM, stack included. The rest of
its slot holds the image header and trailer (§5.3).

RB1-NOTES rev 1.0 · page 4 of 8

<!-- pagebreak -->

## §4 The controller's interface

**§4.1 Link.** UART, 115,200 bit/s, 8 data bits, no parity, 1 stop bit. Each frame is
`0xA5 <type> <length> <payload> <crc8>`, with CRC-8/SMBUS over type, length and payload.

**§4.2 Commands from the main computer.**

| Type | Command | Payload | Effect |
| --- | --- | --- | --- |
| 0x10 | `drive` | speed (int16, mm/s), turn rate (int16, 0.1 °/s) | Sets the target speed and turn rate, limited by §3.3; ignored unless motion is enabled |
| 0x11 | `motion` | 0 or 1 | Enables or disables driving; 0 is always accepted |
| 0x12 | `stop` | none | Target speed and turn rate to 0 |
| 0x20 | `read` | register (uint8, §4.5) | Answers with a `value` frame (0x21) |

**§4.3 Telemetry.** The controller sends a telemetry frame (0x30) every 20 ms: tilt (int16, 0.01°), tilt rate (int16,
0.1 °/s), left and right wheel speed (int16, mm/s), travel (int32, mm), battery voltage (uint16, mV) and flags
(uint16): bit 0 `fallen`, bit 1 `on_stand`, bit 2 `speed_limited`, bit 3 `torque_limited`, bit 4 `motion_enabled`.

**§4.4 Timeout.** When no frame arrives from the main computer for 500 ms while motion is enabled, the controller sets
the target speed and turn rate to 0 and disables motion.

**§4.5 Registers.** All registers are read-only over the link.

| Register | Name | Type | Unit |
| --- | --- | --- | --- |
| 0x01 | Firmware version | uint16 | major × 256 + minor |
| 0x02 | Image sequence number | uint32 | — |
| 0x03 | Guard speed limit | uint16 | mm/s |
| 0x04 | Guard torque limit | uint16 | mN·m |
| 0x05 | Last loop period | uint16 | µs |
| 0x06 | Self-test result | uint8 | bit mask, 0 = all passed |

RB1-NOTES rev 1.0 · page 5 of 8

<!-- pagebreak -->

## §5 Flash layout, images and calibration

**§5.1 Layout.** The controller's flash is divided as follows. An update writes a new image only into the secondary
slot. The bootloader swaps it into the primary slot, through the scratch area, for a trial start (§5.4).

| Partition | Start | Size | Written by |
| --- | --- | --- | --- |
| Bootloader | 0x0000_0000 | 32 KiB | The factory only |
| Calibration | 0x0000_8000 | 4 KiB | The calibration procedure only |
| Reserved | 0x0000_9000 | 28 KiB | Nothing; kept free so that the slots start on a 64 KiB boundary |
| Primary slot | 0x0001_0000 | 256 KiB | The bootloader, when it swaps |
| Secondary slot | 0x0005_0000 | 256 KiB | The flash gate |
| Scratch | 0x0009_0000 | 8 KiB | The bootloader, when it swaps |

**§5.2 Calibration data.** The calibration area holds the IMU's mounting offsets, the gyroscope's bias at the factory
and the balance angle (§2.4). A full erase destroys it, and the robot then cannot balance until it is calibrated
again.

**§5.3 Images.** Every application image starts with a 512-byte header holding its size and a sequence number, and
ends with a trailer holding the SHA-256 of header and image and an ECDSA P-256 signature over them. The bootloader
holds the public key; the private key is held only by the signing step of the build server.

**§5.4 Start.** At every start the bootloader checks the image in the primary slot: size, digest and signature. It
swaps in a new image from the secondary slot only if that image's signature verifies. A swapped-in image runs as a
*trial*: it confirms itself after its self-test (§5.5) passes, by setting the confirmation flag in its image trailer
in the primary slot. If it has not confirmed itself, the next reset, from the failed self-test, the watchdog or the
flash gate's time-out, swaps the previous image back. The bootloader does not compare sequence numbers; the flash gate
refuses an image whose sequence number is lower than the running image's.

**§5.5 Self-test.** Within 2 s of starting, the firmware reads the IMU, runs 10 balance loop cycles with the motors
disabled and checks their period against §3.1, checks that the guard limits of §3.3 are in place and that motion is
disabled. It writes the result to register 0x06 and, if all pass, confirms the image.

RB1-NOTES rev 1.0 · page 6 of 8

<!-- pagebreak -->

## §6 Safe operating conditions

**§6.1 Flashing.** The secondary slot shall be written only when all of these hold: the battery is at 50 % or more;
the robot is on its stand; motion is disabled; a person is present at the robot. A full backup of the controller's
flash is read first, and the written image is read back and compared with its digest.

**§6.2 Moving.** The robot may drive only while motion is enabled (§4.2), which only a person turns on at the operator
console. Motion is disabled after every restart of the controller or the main computer and after every flash.

**§6.3 Software updates.** The main computer's update client shall defer an update while the robot is moving, while
the battery is below 30 %, or while a flash is in progress.

**§6.4 Battery.** The battery percentage is estimated from the voltage: 6.6 V is 0 %, 8.4 V is 100 %, linear between.
On a charger the reading stays at 100 %, so 100 % means "at the top of the scale", not "full".

**§6.5 Pushes.** RB-1 is meant to withstand a push on its body: an impulse up to the *rated push impulse* (*to be
set*, between 0.35 and 0.60 N·s), applied horizontally 0.060 m above the body's centre of mass as a constant force
over 50 ms, from the front or the back, without falling. "Falling" for this purpose is defined in the change request
that uses it, not here.

RB1-NOTES rev 1.0 · page 7 of 8

<!-- pagebreak -->

## §7 Evidence tiers

**§7.1 Tiers.** Every test result about RB-1 is labelled with one of four tiers:

| Tier | Where it runs | What it cannot show |
| --- | --- | --- |
| mock | Unit tests against fakes of the hardware abstraction layer | Physics, timing, the target build |
| simulation | The twin: the host build of the firmware against a physics model | Interrupt timing, the controller's stack use, real sensors and motors |
| emulation | The Cortex-M3 build on an emulated board | Real interrupt timing, sensors and motors |
| device | A real RB-1 | Only the conditions of that test |

**§7.2 Reporting.** A result is never reported at a higher tier than the one it ran at. A twin result names the twin
version and its measured error on the recorded pushes.

RB1-NOTES rev 1.0 · page 8 of 8
