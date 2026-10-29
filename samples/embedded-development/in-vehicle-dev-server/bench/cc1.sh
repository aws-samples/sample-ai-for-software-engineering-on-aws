#!/usr/bin/env bash
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# The emulated CC-1 and its bench on this machine (build plan item 3).
#
# Physical actions (CC1-PN §8.1). Each one passes the physical gate, waits for a person's approval at the operator
# console (bench/console.py) for the build's digest, and goes to the action record. One at a time; an interrupted or
# failed action leaves the target unknown until a person reconciles it at the console.
#   deploy <vstatd>                                       install a build and read its digest back (CC1-PN §8.4)
#   restart                                               start or restart vstatd with the installed build
#   replay --kind run|baseline --out <dir> [--drive <file>]   one replay, written as a run directory (checks/README.md)
# Without approval, recorded:  stop-vstatd
# Reads:                       probe | supply | target | status
# Bench owner only (setup and debugging, never offered to the agents):
#   start [--shift N] | wait [timeout-s] | stop | reset | ssh <command> | put <file> <path> | serial [n]
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
NAME=cc1-bench
SHIFT_DEFAULT=3  # measured 2026-10-29: shift 5 gave log differences of up to 28 ms between runs, shift 3 up to 19 ms

ssh_opts=(-i /secrets/id_ed25519 -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o LogLevel=ERROR -o ConnectTimeout=20)
scp_opts=(-O -q -P 2222 -i /secrets/id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o LogLevel=ERROR)
in_runner() { docker exec "$NAME" "$@"; }
target_sh() { in_runner ssh "${ssh_opts[@]}" root@127.0.0.1 "$@"; }
put() { docker cp "$1" "$NAME:/tmp/upload" && in_runner scp "${scp_opts[@]}" /tmp/upload "root@127.0.0.1:$2"; }
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
gate() { python3 "$here/lib/gate.py" "$@"; }
running() { [[ $(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null) == true ]]; }
need_running() { running || { echo "the emulated CC-1 is not running (bench/cc1.sh start)" >&2; exit 1; }; }
readback() { target_sh 'sha256sum /usr/bin/vstatd 2>/dev/null' | cut -d' ' -f1; }
deployed() { in_runner cat /state/deployed.json 2>/dev/null \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1" 2>/dev/null; }

# The approved action in progress: if this script ends before it is done, the target becomes unknown.
active=""
on_exit() { local rc=$?; [[ -n $active ]] && gate end "$active" failed --detail "bench/cc1.sh exited with $rc" || true; }
trap on_exit EXIT
physical() {  # physical <action> <digest> <detail>
  echo "$1 of $2: approve or refuse it at the operator console (bench/console.py)" >&2
  local rid
  rid=$(gate authorize "$1" "$2" --detail "$3") || exit 1
  gate begin "$rid" "$1" "$2" --pid $$ || exit 1
  active=$rid
}
done_ok() { gate end "$active" ok --detail "$1"; active=""; }
installed_is_approved() {  # the installed build is the approved one, or the target is unknown
  local approved rb
  approved=$(deployed approved_digest) || { echo "no build has been deployed" >&2; exit 1; }
  rb=$(readback)
  if [[ $rb != "$approved" ]]; then
    gate unknown --why "installed build ${rb:-none} is not the approved $approved"; echo "refused: installed build is not the approved one" >&2; exit 1
  fi
  echo "$approved"
}

case ${1:-} in
  deploy)
    bin=${2:?vstatd binary}; [[ -f $bin ]] || { echo "no file $bin" >&2; exit 2; }
    need_running; digest=$(sha "$bin")
    physical deploy "$digest" "$(basename "$bin"), $(wc -c < "$bin" | tr -d ' ') bytes"
    target_sh 'systemctl stop vstatd 2>/dev/null || true'
    put "$bin" /usr/bin/vstatd
    rb=$(target_sh 'chmod 0755 /usr/bin/vstatd && sha256sum /usr/bin/vstatd' | cut -d' ' -f1)
    printf '{"approved_digest":"%s","readback_digest":"%s","approval_request":"%s"}\n' "$digest" "$rb" "$active" \
      | docker exec -i "$NAME" sh -c 'cat > /state/deployed.json'
    [[ $rb == "$digest" ]] || { echo "digest read back $rb differs from the approved $digest: stop (CC1-PN §8.4)" >&2; exit 1; }
    cp "$bin" "$(gate statedir)/builds/$digest"
    done_ok "installed $digest, read back $rb"
    echo "deployed $digest, read back $rb"
    ;;
  restart)
    need_running; approved=$(installed_is_approved)
    physical restart "$approved" "systemctl restart vstatd"
    target_sh 'systemctl restart vstatd && systemctl is-active vstatd' >/dev/null
    done_ok "vstatd restarted with $approved"
    echo "vstatd restarted"
    ;;
  replay)
    shift; kind=""; out=""; drive="$here/drives/drive-01.rec"
    while (( $# )); do case $1 in --kind) kind=$2; shift 2;; --out) out=$2; shift 2;; --drive) drive=$2; shift 2;;
      *) echo "unknown $1" >&2; exit 2;; esac; done
    [[ -n $kind && -n $out ]] || { echo "replay --kind run|baseline --out <dir>" >&2; exit 2; }
    need_running; approved=$(installed_is_approved); rb=$(readback)
    physical replay "$approved" "$(basename "$drive") $(sha "$drive" | cut -c1-12), $kind"
    target_sh 'mkdir -p /var/lib/cc1-bench'
    put "$drive" /var/lib/cc1-bench/drive.rec
    line=$(target_sh /usr/libexec/cc1-bench/run-replay 3600 | grep '^RESULT ') || { echo "replay failed" >&2; exit 1; }
    result=${line#RESULT }
    inv=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["invocation"])' "$result")
    tmp=$(mktemp -d)
    target_sh "journalctl _SYSTEMD_INVOCATION_ID=$inv _SYSTEMD_UNIT=vstatd.service -o cat --no-pager" > "$tmp/log.jsonl"
    in_runner cat /state/qemu-command.txt > "$tmp/qemu-command.txt"
    printf '{"approved_digest":"%s","readback_digest":"%s"}\n' "$approved" "$rb" > "$tmp/deployed.json"
    clients=$(grep -o 'clients .*' "$here/image/br2-external/board/cc1/rootfs-overlay/usr/lib/systemd/system/cc1-clients.service")
    replay_id="$(basename "$drive" .rec)@$(sha "$drive" | cut -c1-12)+$(printf %s "$clients" | shasum -a 256 | cut -c1-8)"
    python3 "$here/runner/make-run-dir.py" --kind "$kind" --out "$out" --log "$tmp/log.jsonl" --result "$result" \
      --qemu-command "$tmp/qemu-command.txt" --deployed "$tmp/deployed.json" --replay-id "$replay_id" --approval "$active"
    rm -rf "$tmp"
    done_ok "replay $replay_id to $out"
    ;;
  stop-vstatd)
    need_running; gate target >/dev/null || { echo "refused: reconcile at the operator console first" >&2; exit 1; }
    target_sh 'systemctl stop vstatd'
    gate record stop-vstatd --detail "systemctl stop vstatd"
    echo "vstatd stopped"
    ;;
  probe)
    if ! running; then echo '{"qemu_running":false,"reachable":false}'; exit 0; fi
    if facts=$(target_sh 'printf "%s|%s|%s" "$(systemctl is-active vstatd)" "$(sha256sum /usr/bin/vstatd 2>/dev/null | cut -d" " -f1)" "$(ls -A /run/vstatd 2>/dev/null | wc -l)"' 2>/dev/null); then
      IFS='|' read -r act dig n <<< "$facts"
      printf '{"qemu_running":true,"reachable":true,"vstatd":"%s","installed_digest":"%s","run_vstatd_entries":%s,"approved_digest":"%s"}\n' \
        "$act" "$dig" "${n:-0}" "$(deployed approved_digest || true)"
    else
      echo '{"qemu_running":true,"reachable":false}'
    fi
    ;;
  supply)  gate supply ;;
  target)  gate target ;;
  status)  docker ps -a --filter "name=^$NAME$" --format '{{.Names}} {{.Status}}'; in_runner cat /state/qemu-command.txt 2>/dev/null || true
           echo "target: $(gate target 2>/dev/null)"; echo "supply: $(gate supply)" ;;
  start)
    shift_n=$SHIFT_DEFAULT
    [[ ${2:-} == --shift ]] && shift_n=${3:?}
    gate can-power || exit 1
    docker build -q -t cc1-bench-runner "$here/runner" >/dev/null
    for v in cc1-run cc1-bench-secrets; do docker volume create "$v" >/dev/null; done
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -d --name "$NAME" -e CC1_ICOUNT_SHIFT="$shift_n" \
      -v "$here":/bench:ro -v cc1-images:/images:ro -v cc1-run:/state -v cc1-bench-secrets:/secrets \
      cc1-bench-runner /bench/runner/qemu-start.sh >/dev/null
    gate fresh-boot --detail "icount shift=$shift_n"
    echo "started $NAME, icount shift=$shift_n"
    ;;
  wait)
    timeout_s=${2:-900}; t0=$(date +%s)
    until target_sh true 2>/dev/null; do
      (( $(date +%s) - t0 < timeout_s )) || { echo "target not reachable after ${timeout_s}s" >&2; exit 1; }
      running || { echo "QEMU exited" >&2; exit 1; }
      sleep 5
    done
    echo "target up after $(( $(date +%s) - t0 ))s (wall clock)"
    ;;
  stop)
    gate can-power || exit 1
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    gate off --why "stopped by the bench owner"
    echo stopped
    ;;
  reset)
    # Back to the known state before a run (CC1-PN §8.3): vstatd stopped, /run/vstatd empty, the last approved build.
    need_running; gate target >/dev/null || { echo "refused: reconcile at the operator console first" >&2; exit 1; }
    target_sh 'systemctl stop vstatd cc1-clients cc1-gwd 2>/dev/null; systemctl reset-failed vstatd cc1-clients cc1-gwd 2>/dev/null; rm -rf /run/vstatd/* /var/lib/cc1-bench/drive.rec; true'
    approved=$(deployed approved_digest || true); rb=$(readback)
    if [[ -z $approved ]]; then detail="no build deployed since the pristine boot"
    elif [[ $rb == "$approved" ]]; then detail="vstatd stopped, /run/vstatd empty, approved build $approved installed"
    else gate unknown --why "reset: installed ${rb:-none} is not the approved $approved"; echo "refused: installed build is not the approved one; deploy it again" >&2; exit 1
    fi
    gate record reset --detail "$detail"
    echo "$detail"
    ;;
  ssh)     shift; target_sh "$@" ;;
  put)     put "$2" "$3" ;;
  serial)  in_runner tail -n "${2:-40}" /state/console.log ;;
  *)       sed -n '3,14p' "$0"; exit 2 ;;
esac
