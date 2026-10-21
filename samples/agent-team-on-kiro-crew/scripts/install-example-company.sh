#!/usr/bin/env bash
# Install the example company, Taoyuan Tech (桃源科技, fictitious), into this Mac and into Kiro Crew. Safe to re-run:
# what exists already is kept.
#
#   bash scripts/install-example-company.sh
#
# Creates: ~/workplace/taoyuan/ (knowledge files, data, brand), 15 Kiro agent templates in ~/.kiro/agents/, the Kiro
# Crew workspace "taoyuan", 15 members (Customize -> Teammates) and the knowledge source "桃源科技". A template that
# already exists with other content is backed up to ~/.kiro/agents/.aidlc-team-sample-backup/ before it is replaced.
# Everything it creates is recorded in .install-state.json, and cleanup.sh removes only that.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
source "$ROOT/scripts/lib.sh"
SRC="$ROOT/example-company"
state() { "$PY" "$ROOT/scripts/state.py" "$@"; }   # what this script created: see scripts/state.py
BACKUP="$HOME/.kiro/agents/.aidlc-team-sample-backup"

# The member templates name the kirocrew program by its full path (its MCP server answers the knowledge searches).
# After a Kiro Crew update the path can change: re-run this script.
ARCH="$([ "$(uname -m)" = arm64 ] && echo arm64 || echo x64)"
KIROCREW_BIN="$(crew_app_dir)/Contents/Resources/backend-dist/kirocrew-backend-$ARCH/bin/kirocrew"
[ -x "$KIROCREW_BIN" ] || { echo "Cannot find the kirocrew program at $KIROCREW_BIN: open Kiro Crew first" >&2; exit 1; }

echo "1/5 Knowledge files and data -> $COMPANY_HOME"
[ -e "$COMPANY_HOME" ] || state add created company_home
mkdir -p "$COMPANY_HOME/brand"
rsync -a --delete --exclude .DS_Store "$SRC/knowledge/" "$COMPANY_HOME/knowledge/"
rsync -a --delete --exclude .DS_Store "$SRC/data/" "$COMPANY_HOME/data/"
cp "$SRC/brand/mascot.svg" "$COMPANY_HOME/brand/mascot.svg"

echo "2/5 Agent templates -> ~/.kiro/agents/ (14 AI-DLC experts and 1 company expert)"
TPL="$(mktemp -d)"
"$PY" "$SRC/agents/make_templates.py" "$ROOT/vendor/aidlc-workflows/agents" "$TPL" "$KIROCREW_BIN"
mkdir -p "$HOME/.kiro/agents"
for f in "$TPL"/*.json; do
  name="$(basename "$f" .json)"; dst="$HOME/.kiro/agents/$name.json"
  if [ ! -e "$dst" ]; then
    state add templates "$name"
  elif ! cmp -s "$f" "$dst" && ! state has templates "$name" && [ ! -e "$BACKUP/$name.json" ]; then
    mkdir -p "$BACKUP" && cp -p "$dst" "$BACKUP/$name.json" && state add backed_up "$name"
    echo "   $name.json existed with other content: backed up to $BACKUP/"
  fi
  cp "$f" "$dst"
done
rm -rf "$TPL"

body() { "$PY" -c 'import json,sys; print(json.dumps(dict(a.split("=",1) for a in sys.argv[1:]), ensure_ascii=False))' "$@"; }
post() { local out; out="$("$KC" POST "$1" "$2")"; case "$out" in *'"error"'*) echo "   error: ${out:0:200}" >&2; return 1 ;; esac; }
has() {  # <path> <list key> <field> <value>
  "$KC" GET "$1" | "$PY" -c "import json,sys; d=json.load(sys.stdin); items=d.get(sys.argv[1], d) if isinstance(d, dict) else d; sys.exit(0 if any(str(x.get(sys.argv[2]))==sys.argv[3] for x in items) else 1)" "$2" "$3" "$4"
}

echo "3/5 Kiro Crew workspace $WORKSPACE"
if has /api/workspaces workspaces name "$WORKSPACE"; then echo "   exists"; else
  post /api/workspaces "$(body name="$WORKSPACE" dir="$COMPANY_HOME")" && state add created workspace
fi

echo "4/5 Team members (workspace $WORKSPACE)"
for m in "${MEMBERS[@]}"; do
  if has /api/agents agents name "$m"; then echo "   $m exists"; continue; fi
  desc="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["description"])' "$HOME/.kiro/agents/$m.json")"
  post /api/agents "$(body name="$m" kiro_agent="$m" workspace="$WORKSPACE" display_name="${desc%% · *}" description="$desc")"
  state add members "$m"
  echo "   + $m"
done

echo "5/5 Knowledge source $KNOWLEDGE"
if has /api/knowledge/sources sources name "$KNOWLEDGE"; then echo "   exists"; else
  sid="$("$KC" POST /api/knowledge/sources "$(body name="$KNOWLEDGE" source_type=local_folder uri="$COMPANY_HOME/knowledge")" \
         | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print((d.get("source") or d).get("id"))')"
  "$KC" POST "/api/knowledge/sources/$sid/confirm" '{}' >/dev/null
  state add created knowledge
  echo "   + added; Kiro Crew is indexing it (Knowledge -> Sources shows the progress)"
fi
