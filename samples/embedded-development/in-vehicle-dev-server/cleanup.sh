#!/usr/bin/env bash
# Remove what setup.sh created: bash cleanup.sh
#
#   bash cleanup.sh             # lists what it will remove, then asks you to type "remove"
#   bash cleanup.sh --dry-run   # lists it and stops
#
# It removes only what .install-state.json records as created by setup.sh, and puts back the agent templates setup.sh
# replaced. An app, members, templates, a workspace, a knowledge source or files that existed before setup are left
# alone; so is one of the same name you made after setup (cleanup.sh checks the id, or where it points). When a step
# fails it says so, keeps the record of what is still there and exits 1: fix it and run cleanup.sh again. It does not
# touch Kiro Crew itself or its other settings, and it leaves the Docker images and volumes, the bench state
# (~/.cc1-bench), the baseline and the servers-mode folder alone: it prints the commands that remove them, and what
# only you can remove.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
source "$ROOT/scripts/lib.sh"
DRY=0
[ "${1:-}" = --dry-run ] && DRY=1
created() { state has created "$1"; }
forget() { state remove "$@"; }
FAILED=0
fail() { warn "$*"; FAILED=1; }
members=($(state list members)); templates=($(state list templates)); backed_up=($(state list backed_up))

# GET <path>: the list under <key> (or the reply itself, when it is a list) holds an item with every <field>=<value>
# given. Exit 1 when not, 3 when Kiro Crew did not answer that way.
match() {
  local path="$1" key="$2" rc=0; shift 2
  "$KC" GET "$path" 2>/dev/null | "$PY" -c 'import json,sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(3)
rows = d if isinstance(d, list) else d.get(sys.argv[1]) if isinstance(d, dict) else None
if not isinstance(rows, list):
    sys.exit(3)
want = dict(a.split("=", 1) for a in sys.argv[2:])
sys.exit(0 if any(isinstance(r, dict) and all(str(r.get(k)) == v for k, v in want.items()) for r in rows) else 1)' \
    "$key" "$@" || rc=$?
  return "$rc"
}

# The first of the app's runs (GET /runs, the board's list) that has not ended: print its id and exit 0; 1 when all
# have, 3 when the app did not list them. Ended is the app's own: team.py ENDED (done, failed, stopped), as
# cleanup_sessions in service.py counts them. A hidden run is not listed, and only an ended run can be hidden.
going() {
  local rc=0
  "$KC" GET "/api/apps/$APP/runs" 2>/dev/null | "$PY" -c 'import json,sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(3)
rows = d.get("runs") if isinstance(d, dict) else None
if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("status"), str) for r in rows):
    sys.exit(3)
rid = next((str(r.get("id")) for r in rows if r["status"] not in ("done", "failed", "stopped")), None)
if rid is None:
    sys.exit(1)
print(rid)' || rc=$?
  return "$rc"
}

# remove <what> <GET path> <list key> <DELETE path> <identity: field=value ...>: delete it if it is still the one
# setup made
remove_if_ours() {
  local what="$1" list="$2" key="$3" del="$4" rc=0; shift 4
  match "$list" "$key" "$@" || rc=$?
  case "$rc" in
    0) "$KC" DELETE "$del" >/dev/null 2>&1 || true
       rc=0; match "$list" "$key" "$@" || rc=$?
       [ "$rc" = 1 ] && { ok "$what removed"; return 0; }
       fail "$what not removed: remove it in Kiro Crew and run cleanup.sh again"; return 1 ;;
    1) ok "$what: not there any more, or not the one setup.sh created (kept)"; return 0 ;;
    *) fail "Kiro Crew did not list it: $what not removed"; return 1 ;;
  esac
}

bench_note() {
  echo
  echo "${B}Not removed:${N} the build container, the bench and its state. To remove them too (bench/README.md, Cleanup):"
  echo "    bench/cc1.sh stop"
  echo "    docker volume rm cc1-images cc1-sysroot cc1-br-dl cc1-br-work cc1-run cc1-bench-secrets cc1-build-out \\"
  echo "      vstatd-standin-sysroot"
  echo "    docker image rm cc1-image-builder cc1-bench-runner \\"
  echo "      vstatd-build:amd64 vstatd-build:arm64   # the one you built"
  echo "    rm -rf ~/.cc1-bench            # the bench state, including the action record"
  echo "    rm -rf $RUNS/baseline   # the baseline the bench owner wrote"
  echo "    rm -rf $RUNS/server   # servers mode (app/README): its venv, configs, work tree and the servers' state"
  echo "${B}Left for you:${N}"
  echo "  - the chat folder 「AI-DLC 团队」 in the Kiro Crew sidebar: only a person can delete a folder, so the app hid"
  echo "    the run folders in it. Delete it there (the agent-team sample's app makes one of the same name: delete the"
  echo "    one with the vstatd runs)."
  echo "  - npm's shared cache (~/.npm), and the Python caches (__pycache__) the app and the checks wrote in this"
  echo "    folder."
}

echo "${B}This removes what setup.sh created here:${N}"
if created app; then
  echo "  - the app $APP, the sessions it opened (of every run), its data ($APP_DATA)"
  echo "    and the run repositories and their results ($RUNS/runs); uninstalling it drops its trust and consent"
elif created sample_record; then
  echo "  - the record of this folder in the app's data ($APP_DATA/data/sample.json)"
fi
if state has found app; then
  echo "  - nothing of the app $APP itself: it was installed before setup.sh and stays (setup.sh updated it from here)"
  if created consent; then
    echo "    and keeps the session-approval consent setup.sh sent: uninstall it in Kiro Crew -> Apps to drop it"
  fi
fi
created trust && ! created app && echo "  - the app $APP's entry in Kiro Crew's trusted apps, which setup.sh added"
[ ${#members[@]} -gt 0 ] && echo "  - ${#members[@]} Kiro Crew members, those still in the workspace $WORKSPACE:" \
  "${members[*]:-}"
created workspace && echo "  - the Kiro Crew workspace $WORKSPACE, if it still points to $TEAM_HOME"
created knowledge && echo "  - the Kiro Crew knowledge source $KNOWLEDGE that setup.sh added"
[ ${#templates[@]} -gt 0 ] && echo "  - ${#templates[@]} agent templates in $AGENTS/: ${templates[*]:-}"
[ ${#backed_up[@]} -gt 0 ] && echo "  - and puts back ${#backed_up[@]} agent templates it replaced: ${backed_up[*]:-}"
if created team_home || created knowledge_dir; then
  if "$PY" -c 'import json,sys
sys.exit(0 if isinstance(json.load(open(sys.argv[1])).get("knowledge_files"), dict) else 1)' \
       "${VSTATD_INSTALL_STATE:-$ROOT/.install-state.json}" 2>/dev/null; then
    echo "  - the knowledge copy in $TEAM_HOME/knowledge (files you added or changed stay)"
  else  # an earlier setup's copy, with no record of the files: it overwrote these paths on every run
    echo "  - the knowledge copy in $TEAM_HOME/knowledge: every file at a path knowledge/ has, whatever it holds now"
    echo "    (an earlier setup.sh wrote it and kept no record of the files); files you added at other paths stay"
  fi
fi
for d in node_modules dist; do
  created "ui_$d" && echo "  - app/ui/$d (setup.sh built the board), once the app is gone"
done
if state empty; then echo "  nothing: setup.sh has recorded nothing in this folder"; bench_note; exit 0; fi
[ "$DRY" = 1 ] && { echo "(dry run: nothing removed)"; bench_note; exit 0; }
read -r -p "  Type remove and press Return to go on (anything else stops): " a
[ "$a" = remove ] || { echo "  Nothing removed."; exit 0; }

step 1/2 "Kiro Crew"
# kcapi.sh's token, where it finds no desktop app (Linux)
KC_KIROCREW="${KC_KIROCREW:-$(kirocrew_bin 2>/dev/null || true)}"; export KC_KIROCREW
crew_up || {
  warn "Kiro Crew is not running: $CREW_START and run cleanup.sh again to remove the app, members, knowledge" \
    "source and workspace"
  exit 1
}
[ "$("$KC" --status GET /api/version 2>/dev/null)" = 200 ] || {  # a 200: signed out, Kiro Crew answers a 404 here
  bad "Kiro Crew answers, but its API refused this shell as the dashboard owner: nothing removed."
  echo "    Run cleanup.sh in your own terminal, not from an agent's shell (or Kiro Crew is signed out: sign in first)."
  exit 1
}
APP_GONE=0
no_answer() { fail "Kiro Crew did not say whether the app $APP is installed: $*"; }
APP_RC=1   # installed: 0 it is, 1 it is not, 3 Kiro Crew did not say
if created app || state has found app; then
  APP_RC=0; installed || APP_RC=$?
fi
if [ "$APP_RC" = 3 ]; then
  # Kiro Crew did not say whether the app is there, so a run of it can be going: keep everything, as going's own 3 does
  no_answer "nothing removed: run cleanup.sh again"
  echo "    Nothing removed: the app, its sessions, its data and the record of what setup.sh created stay."
  exit 1
fi
if [ "$APP_RC" = 0 ]; then
  # a run still going keeps everything (its sessions, and the templates and knowledge its roles use), whether
  # setup.sh installed the app or found it installed
  rc=0; rid="$(going)" || rc=$?
  if [ "$rc" != 1 ]; then
    if [ "$rc" = 0 ]; then fail "run $rid is still going: stop it on the board, then run cleanup.sh again"
    else fail "the app $APP did not list its runs: enable it in Kiro Crew -> Apps and run cleanup.sh again"; fi
    echo "    Nothing removed: the app, its sessions, its data and the record of what setup.sh created stay."
    exit 1
  fi
fi
if created app; then
  rc="$APP_RC"
  if [ "$rc" = 0 ]; then
    # every run's sessions (the board's own 清理 keeps the running and signed ones), while the app still answers
    out="$("$KC" POST "/api/apps/$APP/sessions/cleanup" '{"all": true}' 2>&1 || true)"
    # an app older than this folder ignores "all" and keeps the running and signed runs' sessions: kept_runs says so
    if printf '%s' "$out" | "$PY" -c 'import json,sys; d=json.load(sys.stdin)
sys.exit(0 if d.get("ok") and not d.get("failed") and not d.get("kept_runs") else 1)' 2>/dev/null; then
      ok "the app's sessions removed"
      "$KC" POST "/api/apps/$APP/disable" '{}' >/dev/null 2>&1 || true
      # Kiro Crew 0.12.2 answers the DELETE below with a 405: uninstall it through the POST route, and fall back to
      # the DELETE for a Kiro Crew that has no such route. Either way, installed() below says what was removed.
      out="$("$KC" --status POST "/api/apps/$APP/uninstall" '{}' 2>/dev/null || true)"
      case "$out" in
        2??) out="uninstall: $out" ;;
        *) out="uninstall: ${out:-no answer}; delete: $("$KC" DELETE "/api/apps/$APP" 2>/dev/null || true)" ;;
      esac
      rc=0; installed || rc=$?
      case "$rc" in
        1) ok "app removed"; APP_GONE=1 ;;
        0) fail "app not uninstalled: remove it in Kiro Crew -> Apps (${out:0:80})" ;;
        *) no_answer "its data ($APP_DATA) kept: run cleanup.sh again" ;;
      esac
    else
      fail "the app's sessions were not all removed (${out:0:80}):"
      case "$out" in *'"kept_runs": ['[!\]]*)
        echo "    the installed app is older than this folder and keeps some runs' sessions: run setup.sh to update it,"
        echo "    then cleanup.sh again" ;;
      esac
      echo "    enable the app in Kiro Crew -> Apps and run cleanup.sh again (or delete its sessions in the sidebar,"
      echo "    uninstall it in Kiro Crew -> Apps, and run cleanup.sh again)"
    fi
  elif [ "$rc" = 1 ]; then
    ok "app not installed any more (sessions it left, if any: delete them in the sidebar)"; APP_GONE=1
  else
    no_answer "the app, its sessions and its data ($APP_DATA) kept: run cleanup.sh again"
  fi
  [ "$APP_GONE" = 1 ] && forget created app && forget created consent
fi
if created trust && ! created app; then  # an uninstall drops the trust; an app that was there before setup keeps it
  rc=0; trusted || rc=$?
  [ "$rc" = 0 ] && { "$KC" DELETE "/api/security/trusted-apps/$APP" >/dev/null 2>&1 || true; rc=0; trusted || rc=$?; }
  case "$rc" in
    1) ok "trust removed"; forget created trust ;;
    0) fail "$APP is still a trusted app: remove it in Kiro Crew's settings" ;;
    *) fail "Kiro Crew did not list its trusted apps: $APP's trust entry not removed" ;;
  esac
fi
state has found app && forget found app && forget created consent
for m in ${members[@]+"${members[@]}"}; do
  remove_if_ours "member $m" /api/agents agents "/api/agents/$m" name="$m" kiro_agent="$m" workspace="$WORKSPACE" \
    && forget members "$m"
done
if created knowledge; then
  sid="$(state list knowledge_id | head -1)"
  rc=0; ids="$("$KC" GET /api/knowledge/sources 2>/dev/null | "$PY" -c 'import json,sys
d = json.load(sys.stdin); rows = d.get("sources", d) if isinstance(d, dict) else d
sid, name, uri = sys.argv[1:4]
ours = (lambda r: r.get("id") == sid) if sid else (lambda r: (r.get("name"), r.get("uri")) == (name, uri))
print(next((r["id"] for r in rows if ours(r)), ""))' \
    "$sid" "$KNOWLEDGE" "$TEAM_HOME/knowledge" 2>/dev/null)" || rc=$?
  if [ "$rc" != 0 ]; then fail "Kiro Crew did not list its knowledge sources: knowledge source $KNOWLEDGE not removed"
  elif [ -z "$ids" ]; then ok "knowledge source $KNOWLEDGE: not there any more, or not the one setup.sh created (kept)"
    forget created knowledge; forget knowledge_id
  else
    remove_if_ours "knowledge source $KNOWLEDGE" /api/knowledge/sources sources "/api/knowledge/sources/$ids" \
      id="$ids" && forget created knowledge && forget knowledge_id
  fi
fi
if created workspace; then
  remove_if_ours "workspace $WORKSPACE" /api/workspaces workspaces "/api/workspaces/$WORKSPACE" \
    name="$WORKSPACE" path="$TEAM_HOME" && forget created workspace
fi

step 2/2 "Files"
if [ ${#templates[@]} -gt 0 ] || [ ${#backed_up[@]} -gt 0 ]; then
  if "$PY" "$ROOT/scripts/templates.py" remove "$AGENTS" "$BACKUP" | sed 's/^/   /'; then
    forget templates; forget backed_up
  else
    fail "some agent templates could not be removed or put back (above): their record stays"
  fi
fi
if "$PY" "$ROOT/scripts/knowledge.py" remove "$ROOT/knowledge" "$TEAM_HOME/knowledge" | sed 's/^/   /'; then
  forget created team_home; forget created knowledge_dir
else
  fail "some files of the knowledge copy could not be removed (above): their record stays"
fi
if [ "$APP_GONE" = 1 ]; then
  rm -rf "$RUNS/runs" "$APP_DATA"
  rmdir "$RUNS" 2>/dev/null || true   # kept while it holds the baseline or the servers-mode folder
  forget created sample_record
elif created sample_record && ! created app; then
  rm -f "$APP_DATA/data/sample.json" && forget created sample_record
fi
for d in node_modules dist; do
  created "ui_$d" || continue
  if created app; then continue; fi        # the app is still installed: it runs from this folder
  rc=1; [ "$APP_GONE" = 1 ] || { rc=0; installed || rc=$?; }
  if [ "$rc" = 1 ]; then rm -rf "$ROOT/app/ui/$d"; ok "app/ui/$d removed"
  elif [ "$rc" = 0 ]; then
    warn "kept app/ui/$d: the app $APP stays installed and runs from this folder. Once you uninstall the app in"
    echo "    Kiro Crew -> Apps, delete app/ui/$d yourself (cleanup.sh will not know about it any more)"
  else
    no_answer "app/ui/$d kept"; continue
  fi
  forget created "ui_$d"
done
rm -rf "$ROOT/scripts/__pycache__"   # Python's caches there, whoever wrote them (an earlier setup, a test run)
rm -f "${KC_JAR:-${TMPDIR:-/tmp}/kc-cookies-${KC_PORT}.jar}"   # the owner cookie kcapi.sh kept, wherever it keeps it
if [ "$FAILED" = 1 ]; then
  echo
  bad "Not everything was removed. ${VSTATD_INSTALL_STATE:-$ROOT/.install-state.json} keeps what is left: fix what"
  echo "    is above and run cleanup.sh again."
  bench_note
  exit 1
fi
rm -f "${VSTATD_INSTALL_STATE:-$ROOT/.install-state.json}"
ok "removed"
bench_note
echo
echo "${B}Done.${N} To install again: bash setup.sh"
