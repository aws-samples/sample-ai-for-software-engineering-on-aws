#!/bin/bash
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Validates the hw plugin with the official AI-DLC plugin tools and runs their compose test; on Kiro harnesses it also
# composes the plugin into a copy of an install and checks where its steps land. Needs bun, python3 and a packaged
# AI-DLC harness (in an aidlc-workflows checkout, `bun scripts/package.ts`, then dist/<harness>):
#   tests/verify.sh <aidlc-workflows>/dist/kiro-ide kiro-ide
# Works on copies only and removes them; exits non-zero on the first failing step.
set -euo pipefail
dist=$(cd "${1:?packaged harness directory, for example dist/kiro-ide}" && pwd)
harness=${2:?harness name: kiro, kiro-ide, claude, codex, ...}
plugin=$(cd "$(dirname "$0")/.." && pwd)
case "$harness" in
    kiro | kiro-ide) hdir=.kiro ;;
    claude) hdir=.claude ;;
    codex) hdir=.codex ;;
    cursor) hdir=.cursor ;;
    opencode) hdir=.opencode ;;
    copilot) hdir=.aidlc ;;
    *) echo "unknown harness $harness" >&2; exit 2 ;;
esac
[ -d "$dist/$hdir/tools" ] || { echo "$dist has no $hdir/tools: not a packaged $harness harness" >&2; exit 2; }
tools="$dist/$hdir/tools"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

bun "$tools/aidlc-plugin-validate.ts" "$plugin"
# The compose test works on its own copy; it gets a copy too, so that nothing can touch the packaged harness.
cp -R "$dist" "$work/install-test"
bun "$tools/aidlc-plugin-test.ts" "$plugin" --install "$work/install-test" --harness "$harness"

# The placement checks compose the way Kiro installs a plugin (folder drop, then the compose hook). Other harnesses
# install through their host's plugin store; for them the official test above is the check.
case "$harness" in
    kiro | kiro-ide) ;;
    *) echo "placement checks run on kiro and kiro-ide only; $harness: validate and compose test passed"; exit 0 ;;
esac
bun "$tools/aidlc-plugin-build.ts" "$plugin" "$harness" "$work/build"
cp -R "$dist" "$work/install"
cp -R "$work/build/$hdir/." "$work/install/$hdir/"
AIDLC_PLUGIN_ROOT="$work/install/$hdir/aidlc-plugins/hw" AIDLC_PROJECT_DIR="$work/install" AIDLC_HARNESS_DIR="$hdir" \
    bun "$work/install/$hdir/aidlc-plugins/hw/hooks/compose.ts"
python3 "$plugin/tests/check_compose.py" "$dist" "$work/install" "$hdir"
