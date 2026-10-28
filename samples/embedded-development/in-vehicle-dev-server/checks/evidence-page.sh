#!/bin/sh
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# checks/evidence-page.sh: see checks/README.md. Exits 0 when the page is written, 2 on a usage error.
exec python3 "$(dirname "$0")/lib/evidence_page.py" "$@"
