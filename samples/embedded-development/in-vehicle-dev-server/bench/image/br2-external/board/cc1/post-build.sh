#!/usr/bin/env bash
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Buildroot post-build script: $1 is the target directory.
set -euo pipefail
TARGET_DIR=$1
units=$TARGET_DIR/usr/lib/systemd/system

# The vstatd unit of the reference project (CC1-PN §4.2, §3). Installed but not enabled: the bench starts vstatd for
# each run and keeps it stopped otherwise (CC1-PN §8.3).
install -D -m 0644 "${CC1_SAMPLE_DIR:?}/reference-project/systemd/vstatd.service" "$units/vstatd.service"

# Install the bench's SSH key from fw_cfg before dropbear starts.
mkdir -p "$TARGET_DIR/etc/systemd/system/multi-user.target.wants"
ln -sf /etc/systemd/system/cc1-bench-key.service \
  "$TARGET_DIR/etc/systemd/system/multi-user.target.wants/cc1-bench-key.service"
