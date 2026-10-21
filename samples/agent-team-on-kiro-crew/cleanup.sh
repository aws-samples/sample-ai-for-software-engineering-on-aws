#!/usr/bin/env bash
# Remove what setup.sh created: bash cleanup.sh
#
#   bash cleanup.sh             # lists what it will remove, then asks you to type "remove"
#   bash cleanup.sh --dry-run   # lists it and stops
#
# It removes only what .install-state.json records as created by setup.sh in this folder, and puts back the agent
# templates setup.sh replaced. Members, templates, a workspace or a knowledge source that existed before setup are
# left alone. It does not touch this folder, Kiro Crew itself or its other settings.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
source "$ROOT/scripts/lib.sh"
state() { "$PY" "$ROOT/scripts/state.py" "$@"; }
DRY=0
[ "${1:-}" = --dry-run ] && DRY=1
APP_DATA="$HOME/.kiro/crew/apps/aidlc-team"   # the installed app and its data: runs, events, sign-offs
RUNS="$HOME/workplace/aidlc-team"             # the git repositories and worktrees of every run
BACKUP="$HOME/.kiro/agents/.aidlc-team-sample-backup"
created() { state has created "$1"; }
members=($(state list members)); templates=($(state list templates)); backed_up=($(state list backed_up))

echo "${B}This removes what setup.sh created here:${N}"
if created app; then
  echo "  - the app aidlc-team (stopping any site it deployed), the sessions it opened, its data ($APP_DATA)"
  echo "    and the run repositories ($RUNS)"
fi
[ ${#members[@]} -gt 0 ] && echo "  - ${#members[@]} Kiro Crew members: ${members[*]:-}"
created workspace && echo "  - the Kiro Crew workspace $WORKSPACE"
created knowledge && echo "  - the Kiro Crew knowledge source $KNOWLEDGE"
[ ${#templates[@]} -gt 0 ] && echo "  - ${#templates[@]} agent templates in ~/.kiro/agents/"
[ ${#backed_up[@]} -gt 0 ] && echo "  - and puts back ${#backed_up[@]} agent templates it replaced: ${backed_up[*]:-}"
created company_home && echo "  - $COMPANY_HOME"
if [ ! -s "$ROOT/.install-state.json" ]; then echo "  nothing: setup.sh has recorded nothing in this folder"; exit 0; fi
[ "$DRY" = 1 ] && { echo "(dry run: nothing removed)"; exit 0; }
read -r -p "  Type remove and press Return to go on (anything else stops): " a
[ "$a" = remove ] || { echo "  Nothing removed."; exit 0; }

step 1/2 "Kiro Crew"
if crew_up; then
  if created app; then
    "$KC" POST /api/apps/aidlc-team/sessions/cleanup '{}' >/dev/null 2>&1 || true
    "$KC" POST /api/apps/aidlc-team/disable '{}' >/dev/null 2>&1 || true   # stops the site the app deployed
    out="$("$KC" DELETE /api/apps/aidlc-team 2>/dev/null || true)"
    case "$out" in *rror*) warn "app not uninstalled: remove it in Kiro Crew -> Apps (${out:0:80})" ;; *) ok "app removed" ;; esac
  fi
  n=0
  for m in ${members[@]+"${members[@]}"}; do
    member_present "$m" 2>/dev/null && "$KC" DELETE "/api/agents/$m" >/dev/null 2>&1 && n=$((n + 1))
  done
  [ ${#members[@]} -gt 0 ] && ok "$n members removed"
  if created knowledge; then
    sid="$("$KC" GET /api/knowledge/sources | "$PY" -c 'import json,sys; d=json.load(sys.stdin); rows=d.get("sources",d) if isinstance(d,dict) else d; print(next((r["id"] for r in rows if r.get("name")==sys.argv[1]), ""))' "$KNOWLEDGE" 2>/dev/null || true)"
    if [ -n "$sid" ]; then "$KC" DELETE "/api/knowledge/sources/$sid" >/dev/null 2>&1 && ok "knowledge source removed" || warn "remove the knowledge source $KNOWLEDGE in Kiro Crew -> Knowledge -> Sources"; fi
  fi
  if created workspace; then
    out="$("$KC" DELETE "/api/workspaces/$WORKSPACE" 2>/dev/null || true)"
    case "$out" in *rror*) warn "workspace $WORKSPACE not removed (${out:0:80})" ;; *) ok "workspace removed" ;; esac
  fi
else
  warn "Kiro Crew is not running: open it and run cleanup.sh again to remove the app, members, knowledge source and workspace"
  exit 1
fi

step 2/2 "Files"
for t in ${templates[@]+"${templates[@]}"}; do rm -f "$HOME/.kiro/agents/$t.json" "$HOME/.kiro/agents/$t.lock"; done
for t in ${backed_up[@]+"${backed_up[@]}"}; do [ -f "$BACKUP/$t.json" ] && mv -f "$BACKUP/$t.json" "$HOME/.kiro/agents/$t.json"; done
rmdir "$BACKUP" 2>/dev/null || true
created company_home && rm -rf "$COMPANY_HOME"
created app && rm -rf "$RUNS" "$APP_DATA"
rm -f "${TMPDIR:-/tmp}/kc-cookies-5476.jar" "$ROOT/.install-state.json"
ok "removed"
echo
echo "${B}Done.${N} To install again: bash setup.sh"
