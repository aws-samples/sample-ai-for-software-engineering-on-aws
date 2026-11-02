#!/bin/sh
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Runs cppcheck and clang-tidy with the settings of the team rules (TR §3.1) on a configured cross build's
# compile_commands.json. Run from the project directory, in the build environment:
#   tools/run-analysers.sh build-cross
# Writes build-cross/analysis/cppcheck.txt and build-cross/analysis/clang-tidy.txt, and each tool's exit status in
# cppcheck.rc and clang-tidy.rc (clang-tidy exits non-zero when a file does not compile).
set -eu
build=${1:-build-cross}
out="$build/analysis"
mkdir -p "$out"
cppcheck --version > "$out/versions.txt"
clang-tidy --version | head -n 1 >> "$out/versions.txt"

cppcheck --std=c++17 --library=posix --enable=warning,style,performance,portability --inline-suppr \
  --project="$build/compile_commands.json" --quiet -j "$(nproc)" \
  --template='{file}:{line}:{column}: {severity}: {id}: {message}' 2> "$out/cppcheck.txt" && rc=0 || rc=$?
echo "$rc" > "$out/cppcheck.rc"

files=$(python3 -c 'import json,sys; print("\n".join(sorted({e["file"] for e in json.load(open(sys.argv[1]))})))' \
  "$build/compile_commands.json")
# shellcheck disable=SC2086
clang-tidy -p "$build" --quiet $files > "$out/clang-tidy.txt" 2> "$out/clang-tidy.err" && rc=0 || rc=$?
echo "$rc" > "$out/clang-tidy.rc"
echo "cppcheck: $(grep -c '' "$out/cppcheck.txt") lines, clang-tidy: $(grep -c ': warning: \|: error: ' "$out/clang-tidy.txt") diagnostics"
