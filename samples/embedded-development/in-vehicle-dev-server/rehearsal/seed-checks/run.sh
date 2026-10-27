#!/bin/bash
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Seed checks for facilitators: shows each seeded difficulty of the reference project, and what its "wrong fix"
# does. Run in the build environment (reference-project/tools/Dockerfile), from anywhere:
#   SYSROOT=/opt/cc1-sysroot rehearsal/seed-checks/run.sh
# ThreadSanitizer needs ASLR off on kernels with high mmap randomisation: the script uses `setarch -R`, which in a
# container needs `--security-opt seccomp=unconfined`. Writes logs to $OUT (default: a temporary directory).
set -u
here=$(cd "$(dirname "$0")" && pwd)
sample=$(cd "$here/../.." && pwd)
sysroot=${SYSROOT:-/opt/cc1-sysroot}
out=${OUT:-$(mktemp -d /tmp/vstatd-seed-checks.XXXXXX)}
mkdir -p "$out"
jobs=$(nproc)
results=()
failed=0

note() { printf '%s\n' "$*" | tee -a "$out/summary.txt"; }
result() {  # name, PASS|FAIL, detail
    results+=("| $1 | $2 | $3 |")
    [ "$2" = PASS ] || failed=1
}
copy() {  # fresh copy of the reference project in $out/$1
    rm -rf "${out:?}/$1"
    cp -r "$sample/reference-project" "$out/$1"
    rm -rf "$out/$1"/build*
}
host_build() {  # dir, log, extra cmake args...
    local dir=$1 log=$2
    shift 2
    cmake -S "$dir" -B "$dir/build" -G Ninja "$@" > "$out/$log.log" 2>&1 && ninja -C "$dir/build" -j "$jobs" >> "$out/$log.log" 2>&1
}
patch_text() {  # file, old, new: replace exactly one occurrence or fail
    python3 - "$1" "$2" "$3" <<'PY'
import pathlib, sys
p, old, new = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
s = p.read_text()
if s.count(old) != 1:
    raise SystemExit(f"{p}: expected one occurrence of {old!r}")
p.write_text(s.replace(old, new))
PY
}
count() { grep -c "\"ev\":\"$1\"" "$2"; }

note "seed checks, logs in $out"
note "$(g++ --version | head -n 1); $(aarch64-linux-gnu-g++ --version | head -n 1)"

# 1. Cross build: fails on the target-only header without the sysroot, builds with it (CC1-PN §7.2).
copy cross
cmake -S "$out/cross" -B "$out/cross/build-nosys" -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/cc1-aarch64.cmake \
    > "$out/cross-nosys.log" 2>&1
ninja -C "$out/cross/build-nosys" -j "$jobs" >> "$out/cross-nosys.log" 2>&1
nosys=$?
missing=$(grep -c "systemd/sd-daemon.h: No such file or directory" "$out/cross-nosys.log")
cmake -S "$out/cross" -B "$out/cross/build-sys" -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/cc1-aarch64.cmake \
    -DCMAKE_SYSROOT="$sysroot" > "$out/cross-sys.log" 2>&1 && ninja -C "$out/cross/build-sys" -j "$jobs" >> "$out/cross-sys.log" 2>&1
sys=$?
if [ "$nosys" -ne 0 ] && [ "$missing" -gt 0 ] && [ "$sys" -eq 0 ]; then
    result "Cross build, target-only header" PASS "without sysroot: fails on <systemd/sd-daemon.h>; with $sysroot: builds"
else
    result "Cross build, target-only header" FAIL "without sysroot rc=$nosys (header errors: $missing), with sysroot rc=$sys"
fi

# 2. Data race on the signal table: ThreadSanitizer in the baseline unit tests (TR §2.2).
copy tsan
if host_build "$out/tsan" tsan-build -DVSTATD_SANITIZE=thread; then
    TSAN_OPTIONS="halt_on_error=0" setarch -R "$out/tsan/build/tests/vstatd_tests" > "$out/tsan-test.log" 2>&1
    races=$(grep -c "WARNING: ThreadSanitizer: data race" "$out/tsan-test.log")
    where=$(grep -m1 "SUMMARY: ThreadSanitizer" "$out/tsan-test.log" | sed 's/.*data race //')
    passed=$(grep -c "^\[  PASSED  \]" "$out/tsan-test.log")
    if [ "$races" -ge 1 ] && grep -q "SignalTable::get" "$out/tsan-test.log" && [ "$passed" -eq 1 ]; then
        result "Data race (F-031 to be)" PASS "tests pass; ThreadSanitizer: $races race report(s), $where"
    else
        result "Data race (F-031 to be)" FAIL "races=$races passed=$passed"
    fi
else
    result "Data race (F-031 to be)" FAIL "ThreadSanitizer build failed"
fi

# 3. F-011: the off-by-one in SignalTable::find reads past the table on a miss; AddressSanitizer shows it.
copy asan
if host_build "$out/asan" asan-build -DVSTATD_SANITIZE=address,undefined; then
    "$out/asan/build/tests/vstatd_tests" > "$out/asan-test.log" 2>&1
    base=$?
    g++ -std=c++17 -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer -I"$out/asan/src" \
        "$here/miss_lookup.cpp" "$out/asan/build/libvstatd_core.a" -pthread -o "$out/asan/miss_lookup" \
        > "$out/asan-miss-build.log" 2>&1
    "$out/asan/miss_lookup" > "$out/asan-miss.log" 2>&1
    miss=$?
    if [ "$base" -eq 0 ] && [ "$miss" -ne 0 ] && grep -q "heap-buffer-overflow" "$out/asan-miss.log" &&
        grep -q "SignalTable::find" "$out/asan-miss.log"; then
        result "F-011 out-of-bounds read on a miss" PASS \
            "baseline tests pass under ASan+UBSan; a miss lookup: $(grep -m1 -o 'heap-buffer-overflow[^ ]* on address' "$out/asan-miss.log") in SignalTable::find"
    else
        result "F-011 out-of-bounds read on a miss" FAIL "baseline rc=$base, miss rc=$miss"
    fi
else
    result "F-011 out-of-bounds read on a miss" FAIL "ASan build failed"
fi

# 4. F-008: removing the "always true" condition starts supervision at GATEWAY_CONNECTED.
copy base
copy f008
patch_text "$out/f008/src/supervisor.cpp" "if (entry.supervised && !entry.timed_out" "if (!entry.timed_out"
if host_build "$out/base" base-build && host_build "$out/f008" f008-build; then
    python3 "$here/replay.py" --vstatd "$out/base/build/vstatd" --scenario drive --seconds 3 \
        --log "$out/f008-baseline.jsonl" > "$out/f008-baseline.json"
    python3 "$here/replay.py" --vstatd "$out/f008/build/vstatd" --scenario drive --seconds 3 \
        --log "$out/f008-wrongfix.jsonl" > "$out/f008-wrongfix.json"
    bt=$(count SIGNAL_TIMEOUT "$out/f008-baseline.jsonl"); br=$(count SIGNAL_RECOVERED "$out/f008-baseline.jsonl")
    wt=$(count SIGNAL_TIMEOUT "$out/f008-wrongfix.jsonl"); wr=$(count SIGNAL_RECOVERED "$out/f008-wrongfix.jsonl")
    which=$(grep '"SIGNAL_TIMEOUT"' "$out/f008-wrongfix.jsonl" | sed 's/.*"message":"\([^"]*\)".*/\1/' | tr '\n' ' ')
    if [ "$bt" -eq 0 ] && [ "$br" -eq 0 ] && [ "$wt" -ge 1 ] && [ "$wr" -ge 1 ]; then
        result "F-008 wrong fix changes a timeout" PASS \
            "baseline: $bt SIGNAL_TIMEOUT, $br SIGNAL_RECOVERED; condition removed: $wt and $wr ($which)"
    else
        result "F-008 wrong fix changes a timeout" FAIL "baseline $bt/$br, wrong fix $wt/$wr"
    fi
else
    result "F-008 wrong fix changes a timeout" FAIL "host build failed"
fi

# 5. F-021: value-initialising lines_ makes every client's 64 KiB queue resident (host figures, not target).
copy f021
patch_text "$out/f021/src/client_session.h" "std::array<std::array<char, kMaxLine>, kQueueLines> lines_;" \
    "std::array<std::array<char, kMaxLine>, kQueueLines> lines_{};"
if host_build "$out/f021" f021-build; then
    python3 "$here/replay.py" --vstatd "$out/base/build/vstatd" --clients 16 --seconds 3 > "$out/f021-baseline.json"
    python3 "$here/replay.py" --vstatd "$out/f021/build/vstatd" --clients 16 --seconds 3 > "$out/f021-wrongfix.json"
    b=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["vm_hwm_kib_host"])' "$out/f021-baseline.json")
    w=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["vm_hwm_kib_host"])' "$out/f021-wrongfix.json")
    d=$((w - b))
    if [ "$d" -ge 768 ]; then
        result "F-021 fix raises peak memory" PASS "host VmHWM with 16 clients: $b KiB, with lines_{} $w KiB (+$d KiB)"
    else
        result "F-021 fix raises peak memory" FAIL "host VmHWM $b KiB vs $w KiB (+$d KiB)"
    fi
else
    result "F-021 fix raises peak memory" FAIL "host build failed"
fi

note ""
note "| Seed | Result | Evidence |"
note "| --- | --- | --- |"
for r in "${results[@]}"; do note "$r"; done
exit "$failed"
