#!/usr/bin/env bash
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Builds the emulated CC-1 with Buildroot and exports its images and sysroot (CC1-PN §2.1, §7.2).
# Runs inside the image of Dockerfile; ../build-target.sh starts it with these mounts:
#   /sample          the in-vehicle sample, read-only
#   /br/dl           Buildroot download cache (volume)
#   /br/work         Buildroot source and output (volume)
#   /export/images   kernel, root file system, manifest (volume)
#   /export/sysroot  the sysroot for the cross build (volume, mounted at /opt/cc1-sysroot by the build server)
set -euo pipefail

BR_VERSION=2026.02.3
BR_SHA256=5a59e7501b0b4ec52c41f4bfa79412320e0b37eae5f719605a258e8d0c6fc7fb  # buildroot-2026.02.3.tar.xz.sign
BR_TARBALL=/br/dl/buildroot-${BR_VERSION}.tar.xz
BR_SRC=/br/work/buildroot-${BR_VERSION}
OUT=/br/work/output
EXTERNAL=/sample/bench/image/br2-external

# Parallel jobs: at most one per CPU and one per GiB of memory, so the GCC build fits a small Docker VM.
mem_gib=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 / 1024 ))
jobs=${CC1_JOBS:-$(( $(nproc) < mem_gib ? $(nproc) : mem_gib ))}
(( jobs >= 1 )) || jobs=1

if [[ ! -d $BR_SRC ]]; then
  [[ -f $BR_TARBALL ]] || wget -q -O "$BR_TARBALL.part" "https://buildroot.org/downloads/buildroot-${BR_VERSION}.tar.xz" \
    && { [[ -f $BR_TARBALL ]] || mv "$BR_TARBALL.part" "$BR_TARBALL"; }
  echo "$BR_SHA256  $BR_TARBALL" | sha256sum -c -
  tar -xJf "$BR_TARBALL" -C /br/work
fi

export BR2_DL_DIR=/br/dl
export CC1_SAMPLE_DIR=/sample
make -C "$BR_SRC" O="$OUT" BR2_EXTERNAL="$EXTERNAL" cc1_defconfig
sed -i "s/^BR2_JLEVEL=.*/BR2_JLEVEL=${jobs}/" "$OUT/.config"
make -C "$BR_SRC" O="$OUT" olddefconfig
echo "build: Buildroot ${BR_VERSION}, ${jobs} jobs, started $(date -u +%FT%TZ)"
# The bench tools are a local package: rebuild them from the sample on every build.
make -C "$OUT" cc1-bench-dirclean
make -C "$OUT"

# Export. The sysroot is Buildroot's staging directory: glibc, the libsystemd headers and libraries, the C++ runtime.
rsync -a --delete "$OUT/staging/" /export/sysroot/
# The C++ standard library headers and GCC's own directory are not in staging: Buildroot keeps them with the cross
# toolchain in the host directory. The checks' clang-tidy finds the C++ headers only through a GCC installation in
# the sysroot, under a target name it knows (aarch64-linux-gnu, not Buildroot's aarch64-buildroot-linux-gnu), in the
# multiarch layout: usr/lib/gcc/<target>/<version>, usr/include/c++/<version>, usr/include/<target>/c++/<version>.
gcc_ver=$("$OUT/host/bin/aarch64-buildroot-linux-gnu-gcc" -dumpfullversion)
br_tuple=aarch64-buildroot-linux-gnu
gcc_lib=$OUT/host/lib/gcc/$br_tuple/$gcc_ver
cxx_inc=$OUT/host/$br_tuple/include/c++/$gcc_ver
for d in "$gcc_lib" "$cxx_inc" "$cxx_inc/$br_tuple"; do
  [[ -d $d ]] || { echo "build: not found: $d" >&2; exit 1; }
done
mkdir -p "/export/sysroot/usr/lib/gcc/aarch64-linux-gnu/$gcc_ver" "/export/sysroot/usr/include/c++/$gcc_ver" \
  "/export/sysroot/usr/include/aarch64-linux-gnu/c++/$gcc_ver"
rsync -a --delete --exclude plugin --exclude install-tools "$gcc_lib/" "/export/sysroot/usr/lib/gcc/aarch64-linux-gnu/$gcc_ver/"
rsync -a --delete --exclude "$br_tuple" "$cxx_inc/" "/export/sysroot/usr/include/c++/$gcc_ver/"
rsync -a --delete "$cxx_inc/$br_tuple/" "/export/sysroot/usr/include/aarch64-linux-gnu/c++/$gcc_ver/"
install -m 0644 "$OUT/images/Image" "$OUT/images/rootfs.ext4" /export/images/
ver() { sed -n "s/^$1_VERSION = //p" "$BR_SRC/package/$2/$2.mk" | head -1; }
cat > /export/images/manifest.json <<EOF
{
  "buildroot": "${BR_VERSION}",
  "defconfig": "cc1_defconfig",
  "kernel": "$(sed -n 's/^BR2_LINUX_KERNEL_CUSTOM_VERSION_VALUE="\(.*\)"/\1/p' "$OUT/.config")",
  "glibc": "$(ver GLIBC glibc)",
  "systemd": "$(ver SYSTEMD systemd)",
  "target_gcc": "${gcc_ver}",
  "image_sha256": "$(sha256sum /export/images/Image | cut -d' ' -f1)",
  "rootfs_sha256": "$(sha256sum /export/images/rootfs.ext4 | cut -d' ' -f1)",
  "built": "$(date -u +%FT%TZ)"
}
EOF
cp /export/images/manifest.json /export/sysroot/cc1-sysroot-manifest.json
echo "build: done $(date -u +%FT%TZ)"
cat /export/images/manifest.json
