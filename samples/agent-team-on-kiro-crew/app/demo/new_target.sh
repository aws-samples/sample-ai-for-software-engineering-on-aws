#!/usr/bin/env bash
# Create a fresh git repo for one team run from the built-in team's project template.
#   demo/new_target.sh ~/workplace/signup-site
set -euo pipefail
dest="${1:?usage: new_target.sh <empty-or-missing-dir>}"
if [ -e "$dest" ] && [ -n "$(ls -A "$dest" 2>/dev/null)" ]; then echo "refusing: $dest is not empty" >&2; exit 1; fi
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$dest"
cp -R "$here/target-template/." "$dest/"
git -C "$dest" init -q -b main
git -C "$dest" add -A
git -C "$dest" -c user.name="aidlc-team" -c user.email="team@localhost" commit -q -m "需求：活动报名小站"
echo "created $dest at $(git -C "$dest" rev-parse --short HEAD)"
