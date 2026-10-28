#!/bin/sh
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# checks/release.sh: see checks/README.md. The exit status is the verdict: 0 PASS, 1 FAIL, 3 BLOCKED, 2 usage error.
exec python3 "$(dirname "$0")/lib/check_release.py" "$@"
