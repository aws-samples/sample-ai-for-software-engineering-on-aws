#!/usr/bin/env bash
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# The emulated CC-1 on this machine (build plan item 3). The bench's own entry point; agents reach the target only
# through the bench MCP server (item 5), which calls this script.
#   bench/cc1.sh start [--shift N]                 boot from the pristine image (known state, CC1-PN §8.3)
#   bench/cc1.sh wait [timeout-s]                  wait until the target accepts the bench's SSH key
#   bench/cc1.sh deploy <vstatd> [--approved D]    install a build and read its digest back (CC1-PN §8.4)
#   bench/cc1.sh replay --kind run|baseline --out <dir> [--drive <file>]   one replay, written as a run directory
#   bench/cc1.sh ssh <command> | put <file> <path> | console [n] | status | stop
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
NAME=cc1-bench
SHIFT_DEFAULT=3  # measured 2026-10-29: shift 5 gave log differences of up to 28 ms between runs, shift 3 up to 19 ms

ssh_opts=(-i /secrets/id_ed25519 -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o LogLevel=ERROR -o ConnectTimeout=20)
scp_opts=(-O -q -P 2222 -i /secrets/id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o LogLevel=ERROR)
in_runner() { docker exec "$NAME" "$@"; }
target() { in_runner ssh "${ssh_opts[@]}" root@127.0.0.1 "$@"; }
put() { docker cp "$1" "$NAME:/tmp/upload" && in_runner scp "${scp_opts[@]}" /tmp/upload "root@127.0.0.1:$2"; }
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }

case ${1:-} in
  start)
    shift_n=$SHIFT_DEFAULT
    [[ ${2:-} == --shift ]] && shift_n=${3:?}
    docker build -q -t cc1-bench-runner "$here/runner" >/dev/null
    for v in cc1-run cc1-bench-secrets; do docker volume create "$v" >/dev/null; done
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -d --name "$NAME" -e CC1_ICOUNT_SHIFT="$shift_n" \
      -v "$here":/bench:ro -v cc1-images:/images:ro -v cc1-run:/state -v cc1-bench-secrets:/secrets \
      cc1-bench-runner /bench/runner/qemu-start.sh >/dev/null
    echo "started $NAME, icount shift=$shift_n"
    ;;
  wait)
    timeout_s=${2:-900}; t0=$(date +%s)
    until target true 2>/dev/null; do
      (( $(date +%s) - t0 < timeout_s )) || { echo "target not reachable after ${timeout_s}s" >&2; exit 1; }
      docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null | grep -q true || { echo "QEMU exited" >&2; exit 1; }
      sleep 5
    done
    echo "target up after $(( $(date +%s) - t0 ))s (wall clock)"
    ;;
  deploy)
    bin=${2:?vstatd binary}; digest=$(sha "$bin")
    if [[ ${3:-} == --approved && $digest != "${4:?}" ]]; then
      echo "refused: the build's digest $digest is not the approved one" >&2; exit 1
    fi
    target 'systemctl stop vstatd 2>/dev/null || true'
    put "$bin" /usr/bin/vstatd
    readback=$(target 'chmod 0755 /usr/bin/vstatd && sha256sum /usr/bin/vstatd' | cut -d' ' -f1)
    printf '{"approved_digest":"%s","readback_digest":"%s"}\n' "$digest" "$readback" \
      | docker exec -i "$NAME" sh -c 'cat > /state/deployed.json'
    [[ $readback == "$digest" ]] || { echo "digest read back $readback differs from $digest: stop (CC1-PN §8.4)" >&2; exit 1; }
    echo "deployed $digest, read back $readback"
    ;;
  replay)
    shift; kind=""; out=""; drive="$here/drives/drive-01.rec"
    while (( $# )); do case $1 in --kind) kind=$2; shift 2;; --out) out=$2; shift 2;; --drive) drive=$2; shift 2;;
      *) echo "unknown $1" >&2; exit 2;; esac; done
    [[ -n $kind && -n $out ]] || { echo "replay --kind run|baseline --out <dir>" >&2; exit 2; }
    in_runner test -f /state/deployed.json || { echo "nothing deployed" >&2; exit 1; }
    target 'mkdir -p /var/lib/cc1-bench'
    put "$drive" /var/lib/cc1-bench/drive.rec
    line=$(target /usr/libexec/cc1-bench/run-replay 3600 | grep '^RESULT ') || { echo "replay failed" >&2; exit 1; }
    result=${line#RESULT }
    inv=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["invocation"])' "$result")
    tmp=$(mktemp -d)
    target "journalctl _SYSTEMD_INVOCATION_ID=$inv _SYSTEMD_UNIT=vstatd.service -o cat --no-pager" > "$tmp/log.jsonl"
    in_runner cat /state/qemu-command.txt > "$tmp/qemu-command.txt"
    in_runner cat /state/deployed.json > "$tmp/deployed.json"
    clients=$(grep -o 'clients .*' "$here/image/br2-external/board/cc1/rootfs-overlay/usr/lib/systemd/system/cc1-clients.service")
    replay_id="$(basename "$drive" .rec)@$(sha "$drive" | cut -c1-12)+$(printf %s "$clients" | shasum -a 256 | cut -c1-8)"
    python3 "$here/runner/make-run-dir.py" --kind "$kind" --out "$out" --log "$tmp/log.jsonl" --result "$result" \
      --qemu-command "$tmp/qemu-command.txt" --deployed "$tmp/deployed.json" --replay-id "$replay_id"
    rm -rf "$tmp"
    ;;
  ssh)     shift; target "$@" ;;
  put)     put "$2" "$3" ;;
  console) in_runner tail -n "${2:-40}" /state/console.log ;;
  status)  docker ps -a --filter "name=^$NAME$" --format '{{.Names}} {{.Status}}'; in_runner cat /state/qemu-command.txt 2>/dev/null || true ;;
  stop)    docker rm -f "$NAME" >/dev/null 2>&1 && echo stopped || echo "not running" ;;
  *)       sed -n '3,9p' "$0"; exit 2 ;;
esac
