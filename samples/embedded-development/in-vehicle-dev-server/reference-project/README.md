# vstatd

`vstatd` is the vehicle status service of the CC-1 cockpit computer: it reads CAN frames from the gateway socket,
decodes and supervises the signals of `cc1-gateway.dbc`, serves them to cockpit apps on its IPC socket and writes a
JSON runtime log. Its behaviour is specified in VSTATD-IF rev 1.3 (`../knowledge/vstatd-interface.md`); the platform,
build and resource rules are in `../knowledge/cc1-platform-notes.md` and `../knowledge/team-rules.md`. This is the
current release. All of it is synthetic and was written for the AI-DLC embedded sample.

## Layout

| Path | Contents |
| --- | --- |
| `src/` | The service: `main.cpp` (start-up and stop), `service.*` (gateway side: connection, decoding, supervision, value log), `ipc_server.*` and `client_session.*` (IPC side), `gateway_client.*`, `frame_decoder.*`, `supervisor.*`, `signal_table.*`, `signal_defs.*` (the 24 signals and 9 messages), `log_writer.*`, `config.*` |
| `tests/` | GoogleTest unit tests for the build server; `tests/stubs/systemd/sd-daemon.h` stands in for libsystemd (CC1-PN §7.3) |
| `cmake/cc1-aarch64.cmake` | Cross toolchain file (CC1-PN §7.1) |
| `systemd/vstatd.service` | Service unit (CC1-PN §4.2, §3) |
| `.clang-tidy` | clang-tidy settings of TR §3.1 |
| `tools/` | `Dockerfile` of the build environment, `make-standin-sysroot.py`, `run-analysers.sh`, `match-backlog.py` |

## Build environment

Everything builds in the container of `tools/Dockerfile` (Ubuntu 24.04: GCC 12 for the host and for `aarch64`,
CMake, Ninja, GoogleTest 1.14, cppcheck 2.13, clang-tidy 18):

```bash
docker build -t vstatd-build tools/
docker run --rm -it -v "$PWD":/work -v /opt/cc1-sysroot:/opt/cc1-sysroot:ro vstatd-build
```

The CC-1 sysroot (glibc and the libsystemd headers, CC1-PN §7.2) comes from the Buildroot build of the bench's target
image (build plan item 3) and is expected in `/opt/cc1-sysroot`. Until that build exists, a stand-in made from Ubuntu
24.04 arm64 packages can be unpacked there; nothing is installed into the host system:

```bash
python3 tools/make-standin-sysroot.py /opt/cc1-sysroot
```

## Host build and unit tests

```bash
cmake -S . -B build-host -G Ninja && ninja -C build-host && ctest --test-dir build-host
```

The two sanitizer builds of TR §2.2:

```bash
cmake -S . -B build-tsan -G Ninja -DVSTATD_SANITIZE=thread && ninja -C build-tsan
setarch -R build-tsan/tests/vstatd_tests
cmake -S . -B build-asan -G Ninja -DVSTATD_SANITIZE=address,undefined && ninja -C build-asan
build-asan/tests/vstatd_tests
```

ThreadSanitizer refuses to start on kernels with high address-space randomisation (`unexpected memory mapping`);
`setarch -R` turns randomisation off for the test run. In a container this needs a seccomp profile that allows it,
for example `docker run --security-opt seccomp=unconfined`.

The host build also produces a `vstatd` binary with the test double in place of libsystemd, for trying the service on
the build server.

## Cross build

```bash
cmake -S . -B build-cross -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/cc1-aarch64.cmake && ninja -C build-cross
aarch64-linux-gnu-strip -o build-cross/vstatd.stripped build-cross/vstatd
```

The flags of TR §2.1 (`-Wall -Wextra -Werror -O2 -fstack-protector-strong -D_FORTIFY_SOURCE=2`) are set in
`CMakeLists.txt` for every build.

## Static analysis

On a configured cross build (TR §3.1):

```bash
tools/run-analysers.sh build-cross
tools/match-backlog.py build-cross/analysis ../knowledge/findings-backlog.md
```

`match-backlog.py` maps every finding to the function that contains it and pairs it with its backlog row; it lists
findings that are not in the backlog and backlog rows that the analysers no longer report.

## Running

`vstatd` takes no arguments. The socket paths default to VSTATD-IF §2.1 and §5.1; environment variables override them:

| Variable | Default |
| --- | --- |
| `VSTATD_GATEWAY_SOCKET` | `/run/cc1-gwd/can.sock` |
| `VSTATD_IPC_SOCKET` | `/run/vstatd/vstatd.sock` |
| `VSTATD_IPC_GROUP` | `vstat` (group of the IPC socket; skipped when the group does not exist) |

The runtime log goes to standard output (CC1-PN §5). `SIGTERM` or `SIGINT` stops the service. It runs three threads:
the main thread (start-up, signals), the gateway side (`Service::run()`) and the IPC side (`IpcServer`).
