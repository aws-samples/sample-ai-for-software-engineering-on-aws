#!/usr/bin/env bash
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Starts the emulated CC-1 in the bench runner container (CC1-PN §2.1, §2.2, §8.3). Mounts:
#   /images   cc1-images, read-only: Image, rootfs.ext4, manifest.json
#   /state    cc1-run: the run's copy of the root file system, console log, QEMU command line, monitor socket
#   /secrets  cc1-bench-secrets: the bench's SSH key pair
# Every start begins from the pristine root file system (known state, CC1-PN §8.3).
set -euo pipefail
SHIFT=${CC1_ICOUNT_SHIFT:?set CC1_ICOUNT_SHIFT}
[[ $SHIFT =~ ^[0-9]+$ ]] || { echo "CC1_ICOUNT_SHIFT must be a number (no shift=auto, CC1-PN §2.2)" >&2; exit 2; }

[[ -f /secrets/id_ed25519 ]] || ssh-keygen -q -t ed25519 -N '' -C cc1-bench -f /secrets/id_ed25519
cp /images/rootfs.ext4 /state/rootfs.ext4
rm -f /state/console.log /state/monitor.sock /state/deployed.json

cmd=(qemu-system-aarch64
  -M virt -cpu cortex-a53 -smp 4 -m 512M
  -icount "shift=${SHIFT},sleep=off"
  -kernel /images/Image
  -append "root=/dev/vda rw rootwait console=ttyAMA0"
  -drive file=/state/rootfs.ext4,if=none,format=raw,id=hd0 -device virtio-blk-device,drive=hd0
  -netdev user,id=eth0,hostfwd=tcp:127.0.0.1:2222-:22 -device virtio-net-device,netdev=eth0
  -fw_cfg name=opt/cc1/authorized_keys,file=/secrets/id_ed25519.pub
  -display none -serial file:/state/console.log
  -monitor unix:/state/monitor.sock,server,nowait)
echo "${cmd[*]}" > /state/qemu-command.txt
exec "${cmd[@]}"
