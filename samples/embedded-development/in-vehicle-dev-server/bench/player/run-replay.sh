#!/bin/sh
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# One replay on the emulated CC-1 (CC1-PN §2.2, §8.5), run by the bench over SSH after the build was deployed and its
# digest read back. Prints one line `RESULT {json}` for the bench; the runtime log stays in the journal.
#   run-replay <timeout-s>
set -eu
T=${1:-1800}
END=/run/cc1-gwd/end-of-drive

systemctl stop vstatd cc1-clients cc1-gwd 2>/dev/null || true
systemctl reset-failed vstatd cc1-clients cc1-gwd 2>/dev/null || true

# A marker through the journal and back, so that an empty log means vstatd wrote nothing (checks/README.md).
marker="cc1-bench marker $(cat /proc/sys/kernel/random/uuid)"
echo "$marker" | systemd-cat -t cc1-bench
journalctl --sync
journalctl -t cc1-bench -o cat | grep -qxF "$marker" || { echo "journal marker not read back" >&2; exit 4; }

systemctl start cc1-gwd
cc1-bench wait --file /run/cc1-gwd/can.sock --timeout-s 30
# The clients wait for vstatd's IPC socket to listen and then connect at fixed offsets (CC1-PN §2.2).
systemctl start cc1-clients
systemctl start vstatd
inv=$(systemctl show -p InvocationID --value vstatd)
pid=$(systemctl show -p MainPID --value vstatd)
[ "$pid" -gt 0 ] || { echo "vstatd did not start" >&2; exit 5; }

# At the end of the drive: figures first, then SIGTERM, both inside the guest (CC1-PN §8.5).
fin=$(cc1-bench finish --pid "$pid" --end-marker "$END" --timeout-s "$T")
systemctl stop vstatd
restarts=$(systemctl show -p NRestarts --value vstatd)
systemctl stop cc1-clients cc1-gwd
journalctl --sync
echo "RESULT {\"invocation\":\"$inv\",\"marker\":\"$marker\",\"restarts\":$restarts,\"finish\":$fin}"
