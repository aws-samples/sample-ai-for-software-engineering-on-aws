# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Build environment for vstatd: host compiler for the unit tests, the aarch64 cross compiler, CMake, GoogleTest
# and the static analysers of the team rules. The sysroot is not part of the image (see tools/make-standin-sysroot.py).
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      cmake ninja-build file binutils-aarch64-linux-gnu \
      g++-12 g++-12-aarch64-linux-gnu \
      cppcheck clang-tidy-18 \
      libgtest-dev python3 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && ln -sf /usr/bin/g++-12 /usr/local/bin/g++ \
 && ln -sf /usr/bin/gcc-12 /usr/local/bin/gcc \
 && ln -sf /usr/bin/aarch64-linux-gnu-g++-12 /usr/local/bin/aarch64-linux-gnu-g++ \
 && ln -sf /usr/bin/aarch64-linux-gnu-gcc-12 /usr/local/bin/aarch64-linux-gnu-gcc \
 && ln -sf /usr/bin/clang-tidy-18 /usr/local/bin/clang-tidy

WORKDIR /work
