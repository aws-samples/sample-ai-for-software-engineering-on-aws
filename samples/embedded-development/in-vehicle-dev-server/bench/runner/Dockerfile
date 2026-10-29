# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# The bench runner: QEMU for the emulated CC-1 (CC1-PN §2.1, §2.2) and the SSH client the bench uses to reach it.
# Only the bench has the target's SSH key (volume cc1-bench-secrets); the agents never get a shell here.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends qemu-system-arm openssh-client python3 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /bench
