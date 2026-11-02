#!/usr/bin/env bash
# Install the vstatd team into this Mac and into Kiro Crew (the agent-team sample's install-example.sh, for this
# scenario). Safe to re-run: what exists already is kept.
#
#   bash scripts/install-team.sh             # setup.sh runs it
#   bash scripts/install-team.sh --dry-run   # says what it would do; changes nothing
#
# Creates: ~/workplace/vstatd/knowledge/ (a copy of knowledge/), 4 Kiro agent templates in ~/.kiro/agents/ and the
# Kiro Crew knowledge source "vstatd". No Kiro Crew members: the roles' sessions run the templates. A template that
# already exists with other content is backed up to ~/.kiro/agents/.vstatd-team-sample-backup/ before it is replaced.
# Everything it creates is recorded in .install-state.json, and cleanup.sh removes only that.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
source "$ROOT/scripts/lib.sh"
DRY=0
[ "${1:-}" = --dry-run ] && DRY=1
would() { echo "   (dry run) would $*"; }

# The member templates name the kirocrew program by its full path (its MCP server answers the knowledge searches).
# After a Kiro Crew update the path can change: run setup.sh again.
ARCH="$([ "$(uname -m)" = arm64 ] && echo arm64 || echo x64)"
KIROCREW_BIN="${VSTATD_KIROCREW_BIN:-$(crew_app_dir)/Contents/Resources/backend-dist/kirocrew-backend-$ARCH/bin/kirocrew}"
[ -x "$KIROCREW_BIN" ] || { echo "Cannot find the kirocrew program at $KIROCREW_BIN: open Kiro Crew first" >&2; exit 1; }

echo "1/3 Knowledge -> $TEAM_HOME/knowledge"
if [ "$DRY" = 1 ]; then
  [ -e "$TEAM_HOME" ] && would "update $TEAM_HOME/knowledge from knowledge/" || would "create $TEAM_HOME and copy knowledge/ there"
else
  [ -e "$TEAM_HOME" ] || state add created team_home
  mkdir -p "$TEAM_HOME/knowledge"
  rsync -a --delete --exclude .DS_Store --exclude __pycache__ --exclude tools/ "$ROOT/knowledge/" "$TEAM_HOME/knowledge/"
fi

echo "2/3 Agent templates -> $AGENTS/ (${#TEMPLATES[@]} AI-DLC experts)"
TPL="$(mktemp -d)"
trap 'rm -f "$TPL"/*.json; rmdir "$TPL" 2>/dev/null || true' EXIT
"$PY" "$ROOT/agents/kiro-crew/make_templates.py" "$ROOT/vendor/aidlc-workflows/agents" "$TPL" "$KIROCREW_BIN" >/dev/null
"$PY" "$ROOT/scripts/templates.py" "$([ "$DRY" = 1 ] && echo plan || echo install)" "$TPL" "$AGENTS" "$BACKUP" | sed 's/^/   /'

body() { "$PY" -c 'import json,sys; print(json.dumps(dict(a.split("=",1) for a in sys.argv[1:]), ensure_ascii=False))' "$@"; }
post() { local out; out="$("$KC" POST "$1" "$2")"; case "$out" in *'"error"'*) echo "   error: ${out:0:200}" >&2; return 1 ;; esac; }

echo "3/3 Knowledge source $KNOWLEDGE"
if has /api/knowledge/sources sources name "$KNOWLEDGE"; then echo "   exists"
elif [ "$DRY" = 1 ]; then would "add it ($TEAM_HOME/knowledge) and let Kiro Crew index it"
else
  sid="$("$KC" POST /api/knowledge/sources "$(body name="$KNOWLEDGE" source_type=local_folder uri="$TEAM_HOME/knowledge")" \
         | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("source") or d).get("id"))')"
  "$KC" POST "/api/knowledge/sources/$sid/confirm" '{}' >/dev/null
  state add created knowledge
  echo "   + added; Kiro Crew is indexing it (Knowledge -> Sources shows the progress)"
fi
