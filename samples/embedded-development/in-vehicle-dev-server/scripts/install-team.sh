#!/usr/bin/env bash
# Install the vstatd team into this Mac or Linux host and into Kiro Crew (the agent-team sample's install-example.sh,
# for this scenario). Safe to re-run: what exists already is kept.
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
KIROCREW_BIN="$(kirocrew_bin)" || exit 1

echo "1/3 Knowledge -> $TEAM_HOME/knowledge"
# file by file: a file there that setup did not copy is never replaced or deleted (scripts/knowledge.py)
"$PY" "$ROOT/scripts/knowledge.py" "$([ "$DRY" = 1 ] && echo plan || echo install)" "$ROOT/knowledge" \
  "$TEAM_HOME/knowledge" | sed 's/^/   /'

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
  out="$("$KC" POST /api/knowledge/sources \
         "$(body name="$KNOWLEDGE" source_type=local_folder uri="$TEAM_HOME/knowledge")" || true)"
  sid="$(printf '%s' "$out" \
         | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("source") or d).get("id") or "")' \
         2>/dev/null || true)"
  # recorded before anything else can fail, with its id: cleanup.sh removes this source, not another of the same name
  if [ -n "$sid" ] || has /api/knowledge/sources sources name "$KNOWLEDGE"; then state add created knowledge; fi
  [ -n "$sid" ] && state add knowledge_id "$sid"
  [ -n "$sid" ] || { echo "   error: Kiro Crew did not add the source: ${out:0:200}" >&2; exit 1; }
  post "/api/knowledge/sources/$sid/confirm" '{}' || exit 1
  echo "   + added; Kiro Crew is indexing it (Knowledge -> Sources shows the progress)"
fi
