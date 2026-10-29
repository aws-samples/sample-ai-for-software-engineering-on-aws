#!/usr/bin/env bash
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Checks this host before a session with the bench (build plan item 3). Exit status 0 when nothing FAILs.
#   bench/doctor.sh
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
fails=0
pass() { printf 'PASS  %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; fails=$((fails + 1)); }
in_vol() { docker run --rm "$@"; }

if docker info >/dev/null 2>&1; then
  pass "Docker $(docker info -f '{{.ServerVersion}}'), $(docker info -f '{{.NCPU}}') CPUs, $(( $(docker info -f '{{.MemTotal}}') / 1048576 )) MiB"
  mem=$(docker info -f '{{.MemTotal}}')
  (( mem >= 4000000000 )) || warn "Docker has less than 4 GB of memory: the image build and QEMU may be slow or fail"
else
  fail "Docker is not running"; echo "$fails problem(s)"; exit 1
fi

free_kib=$(df -Pk "$HOME" | awk 'NR == 2 {print $4}')
if (( free_kib < 2 * 1048576 )); then fail "less than 2 GiB free on the host"
elif (( free_kib < 15 * 1048576 )); then warn "$(( free_kib / 1048576 )) GiB free: a rebuild of the target image needs about 13 GB of Docker volume space"
else pass "$(( free_kib / 1048576 )) GiB free on the host"; fi

if python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then pass "$(python3 --version)"
else fail "python3 3.9 or later is needed on the host"; fi
python3 -c 'import cantools, yaml' 2>/dev/null && pass "cantools and PyYAML (for drives/make_drive.py)" \
  || warn "cantools or PyYAML missing: needed only to regenerate the drive"

if docker build -q -t cc1-bench-runner "$here/runner" >/dev/null 2>&1; then
  pass "bench runner image, $(docker run --rm cc1-bench-runner qemu-system-aarch64 --version | head -1)"
else fail "the bench runner image does not build (bench/runner/Dockerfile)"; fi

if in_vol -v cc1-images:/i:ro cc1-bench-runner test -f /i/Image -a -f /i/rootfs.ext4 -a -f /i/manifest.json 2>/dev/null; then
  pass "target image: $(in_vol -v cc1-images:/i:ro cc1-bench-runner cat /i/manifest.json | python3 -c 'import json, sys; m = json.load(sys.stdin); print("Buildroot", m["buildroot"], "Linux", m["kernel"], "built", m["built"])')"
else fail "no target image in the volume cc1-images: run bench/build-target.sh"; fi
if in_vol -v cc1-sysroot:/s:ro cc1-bench-runner test -f /s/usr/include/systemd/sd-daemon.h -a -f /s/usr/lib/libsystemd.so.0 2>/dev/null; then
  pass "sysroot in the volume cc1-sysroot"
else fail "no sysroot in the volume cc1-sysroot: run bench/build-target.sh"; fi

[[ -s $here/drives/drive-01.rec ]] && pass "recorded drive $(shasum -a 256 "$here/drives/drive-01.rec" | cut -c1-12)" \
  || fail "no recorded drive: run bench/drives/make_drive.py"

state=$(python3 "$here/lib/gate.py" statedir)
mode=$(python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$state")
[[ $mode == 0o700 ]] && pass "bench state $state (mode 700)" || fail "bench state $state has mode $mode, not 700"
supply=$(python3 "$here/lib/gate.py" supply)
[[ $supply == null ]] && warn "the supply is not set: set it at the operator console (bench/console.py)" || pass "supply $supply"
t=$(python3 "$here/lib/gate.py" target 2>/dev/null)
case $t in
  *'"unknown"'*|*'"busy"'*) fail "target: $t; reconcile at the operator console" ;;
  *) pass "target: $t" ;;
esac
n=$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import benchstate as b; print(sum(not r["expired"] for r in b.pending()))' "$here/lib")
(( n == 0 )) && pass "no pending requests" || warn "$n pending request(s) at the operator console"

(( fails == 0 )) && echo "doctor: ready" || echo "doctor: $fails problem(s)"
exit $(( fails > 0 ))
