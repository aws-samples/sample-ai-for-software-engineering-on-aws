# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Image builder for the emulated CC-1 (CC1-PN §2.1, §7.2): the host packages Buildroot needs. Everything Buildroot
# builds lives in Docker volumes (see ../build-target.sh), because Buildroot needs a case-sensitive file system.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential bash bc bzip2 ca-certificates cpio diffutils file findutils gawk git gzip make patch perl \
      python3 rsync sed tar unzip wget xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Buildroot refuses to run as root. The image's `ubuntu` user (uid 1000) owns the mount points, so empty named
# volumes mounted there take that ownership.
RUN mkdir -p /br/dl /br/work /export/images /export/sysroot \
 && chown -R ubuntu:ubuntu /br /export
USER ubuntu
WORKDIR /br/work
