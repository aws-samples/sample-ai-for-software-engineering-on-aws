# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Build environment for vstatd: host compiler for the unit tests, the aarch64 cross compiler, CMake, GoogleTest
# and the static analysers of the team rules, and git for the checks (../checks/), which judge committed trees. The
# sysroot is not part of the image (see tools/make-standin-sysroot.py).
#
# One file for both architectures (BuildKit sets TARGETARCH from --platform):
#   docker build --platform linux/arm64 -t vstatd-build:arm64 tools/   # Apple Silicon, arm64 Linux
#   docker build --platform linux/amd64 -t vstatd-build:amd64 tools/   # x86_64
# On amd64 the target compiler is the cross compiler g++-12-aarch64-linux-gnu. On arm64 the host compiler already
# targets aarch64: g++-12 provides /usr/bin/aarch64-linux-gnu-g++-12 and binutils the aarch64-linux-gnu-* tools, so
# the same names work in both images. Build the image for the machine it runs on: an amd64 image under Rosetta cannot
# run ThreadSanitizer at all ("unexpected memory mapping"), so the unit check would always fail.
FROM ubuntu:24.04

ARG TARGETARCH
ARG DEBIAN_FRONTEND=noninteractive
RUN case "${TARGETARCH}" in \
      amd64) target="binutils-aarch64-linux-gnu g++-12-aarch64-linux-gnu" ;; \
      arm64) target="binutils" ;; \
      *) echo "unsupported TARGETARCH '${TARGETARCH}' (build with --platform linux/amd64 or linux/arm64)" >&2; exit 1 ;; \
    esac \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      cmake ninja-build file ${target} \
      g++-12 \
      cppcheck clang-tidy-18 \
      libgtest-dev python3 ca-certificates git \
 && rm -rf /var/lib/apt/lists/* \
 && for f in /usr/bin/g++-12 /usr/bin/gcc-12 /usr/bin/aarch64-linux-gnu-g++-12 /usr/bin/aarch64-linux-gnu-gcc-12 \
             /usr/bin/aarch64-linux-gnu-readelf /usr/bin/aarch64-linux-gnu-strip /usr/bin/clang-tidy-18; do \
      test -x "$f" || { echo "missing $f" >&2; exit 1; }; \
    done \
 && ln -sf /usr/bin/g++-12 /usr/local/bin/g++ \
 && ln -sf /usr/bin/gcc-12 /usr/local/bin/gcc \
 && ln -sf /usr/bin/aarch64-linux-gnu-g++-12 /usr/local/bin/aarch64-linux-gnu-g++ \
 && ln -sf /usr/bin/aarch64-linux-gnu-gcc-12 /usr/local/bin/aarch64-linux-gnu-gcc \
 && ln -sf /usr/bin/clang-tidy-18 /usr/local/bin/clang-tidy

WORKDIR /work
