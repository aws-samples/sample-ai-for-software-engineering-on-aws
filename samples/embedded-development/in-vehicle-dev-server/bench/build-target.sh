#!/usr/bin/env bash
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Builds the emulated CC-1 image and sysroot (build plan item 3) into Docker volumes:
#   cc1-images   Image, rootfs.ext4, manifest.json        (used by the bench)
#   cc1-sysroot  the sysroot of the cross build           (mount at /opt/cc1-sysroot in the build server)
#   cc1-br-dl, cc1-br-work   Buildroot's download cache and work tree; keep them to rebuild quickly
# The first build compiles a GCC, glibc, Linux and systemd and takes a while; later builds reuse the work tree.
#   bench/build-target.sh           build in the foreground
#   bench/build-target.sh --detach  build in a container named cc1-image-build; follow it with docker logs -f
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
sample=$(cd "$here/.." && pwd)

docker build -q -t cc1-image-builder "$here/image" >/dev/null
for v in cc1-br-dl cc1-br-work cc1-images cc1-sysroot; do docker volume create "$v" >/dev/null; done
run=(docker run --rm --name cc1-image-build
     -v "$sample":/sample:ro -v cc1-br-dl:/br/dl -v cc1-br-work:/br/work
     -v cc1-images:/export/images -v cc1-sysroot:/export/sysroot
     cc1-image-builder /sample/bench/image/build-image.sh)
if [[ ${1:-} == --detach ]]; then
  "${run[@]:0:2}" -d "${run[@]:2}"
else
  "${run[@]}"
fi
