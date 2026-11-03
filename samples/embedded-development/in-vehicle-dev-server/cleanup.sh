#!/usr/bin/env bash
# Remove what setup.sh created: bash cleanup.sh
#
#   bash cleanup.sh             # lists what it will remove, then asks you to type "remove"
#   bash cleanup.sh --dry-run   # lists it and stops
#
# It removes only what .install-state.json records as created by setup.sh in this folder, and puts back the agent
# templates setup.sh replaced. Members, templates, a workspace or a knowledge source that existed before setup are
# left alone. It does not touch this folder, Kiro Crew itself or its other settings, and it leaves the Docker images
# and volumes, the bench state (~/.cc1-bench) and the baseline alone: it prints the commands that remove them.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
source "$ROOT/scripts/lib.sh"
DRY=0
[ "${1:-}" = --dry-run ] && DRY=1
created() { state has created "$1"; }
members=($(state list members)); templates=($(state list templates)); backed_up=($(state list backed_up))

bench_note() {
  echo
  echo "${B}Not removed:${N} the build container, the bench and its state. To remove them too (bench/README.md, Cleanup):"
  echo "    bench/cc1.sh stop"
  echo "    docker volume rm cc1-images cc1-sysroot cc1-br-dl cc1-br-work cc1-run cc1-bench-secrets cc1-build-out"
  echo "    docker image rm cc1-image-builder cc1-bench-runner vstatd-build:amd64"
  echo "    rm -rf ~/.cc1-bench            # the bench state, including the action record"
  echo "    rm -rf $RUNS/baseline   # the baseline the bench owner wrote"
}

echo "${B}This removes what setup.sh created here:${N}"
if created app; then
  echo "  - the app $APP, the sessions it opened, its data ($APP_DATA)"
  echo "    and the run repositories and their results ($RUNS/runs)"
elif created sample_record; then
  echo "  - the record of this folder in the app's data ($APP_DATA/data/sample.json)"
fi
[ ${#members[@]} -gt 0 ] && echo "  - ${#members[@]} Kiro Crew members: ${members[*]:-}"
created workspace && echo "  - the Kiro Crew workspace $WORKSPACE"
created knowledge && echo "  - the Kiro Crew knowledge source $KNOWLEDGE"
[ ${#templates[@]} -gt 0 ] && echo "  - ${#templates[@]} agent templates in $AGENTS/: ${templates[*]:-}"
[ ${#backed_up[@]} -gt 0 ] && echo "  - and puts back ${#backed_up[@]} agent templates it replaced: ${backed_up[*]:-}"
created team_home && echo "  - $TEAM_HOME (the knowledge copy)"
if [ ! -s "${VSTATD_INSTALL_STATE:-$ROOT/.install-state.json}" ]; then echo "  nothing: setup.sh has recorded nothing in this folder"; bench_note; exit 0; fi
[ "$DRY" = 1 ] && { echo "(dry run: nothing removed)"; bench_note; exit 0; }
read -r -p "  Type remove and press Return to go on (anything else stops): " a
[ "$a" = remove ] || { echo "  Nothing removed."; exit 0; }

step 1/2 "Kiro Crew"
if crew_up; then
  if created app; then
    "$KC" POST "/api/apps/$APP/sessions/cleanup" '{}' >/dev/null 2>&1 || true
    "$KC" POST "/api/apps/$APP/disable" '{}' >/dev/null 2>&1 || true
    out="$("$KC" DELETE "/api/apps/$APP" 2>/dev/null || true)"
    case "$out" in *rror*) warn "app not uninstalled: remove it in Kiro Crew -> Apps (${out:0:80})" ;; *) ok "app removed" ;; esac
  fi
  n=0
  for m in ${members[@]+"${members[@]}"}; do
    has /api/agents agents name "$m" 2>/dev/null && "$KC" DELETE "/api/agents/$m" >/dev/null 2>&1 && n=$((n + 1))
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
"$PY" "$ROOT/scripts/templates.py" remove "$AGENTS" "$BACKUP" | sed 's/^/   /'
created team_home && rm -rf "$TEAM_HOME"
if created app; then
  rm -rf "$RUNS/runs" "$APP_DATA"
  rmdir "$RUNS" 2>/dev/null || true   # kept while it holds the baseline
elif created sample_record; then
  rm -f "$APP_DATA/data/sample.json"
fi
rm -f "${TMPDIR:-/tmp}/kc-cookies-5476.jar" "${VSTATD_INSTALL_STATE:-$ROOT/.install-state.json}"
ok "removed"
bench_note
echo
echo "${B}Done.${N} To install again: bash setup.sh"
