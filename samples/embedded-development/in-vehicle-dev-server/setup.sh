#!/usr/bin/env bash
# Install the Kiro Crew app of this scenario into the Kiro Crew running on this Mac: bash setup.sh
#
#   bash setup.sh                               # asks once whether the app may auto-approve the sessions it opens
#   bash setup.sh --consent-session-approval    # the same, answering yes without asking
#   bash setup.sh --dry-run                     # checks the prerequisites and says what it would do; changes nothing
#
# Safe to re-run: what exists already is kept, the app is updated in place. What this script creates is recorded in
# .install-state.json, and cleanup.sh removes only that. Keep this folder where it is after setup: Kiro Crew installs
# the app from it, and the app runs the checks and the bench from it (it records this folder's path). After a move,
# run setup.sh again.
#
# It does not build the build container, the emulated target or the bench (D10 in docs/kiro-crew-app.md): it prints
# the commands for them at the end.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
source "$ROOT/scripts/lib.sh"
CONSENT=""; DRY=0
for a in "$@"; do
  case "$a" in
    --consent-session-approval) CONSENT="--consent-session-approval" ;;
    --dry-run) DRY=1 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

step 1/5 "Prerequisites"
[ "$(uname -s)" = Darwin ] && ok "macOS $(sw_vers -productVersion) ($(uname -m))" || { bad "setup.sh runs on macOS (Kiro Crew's desktop app)"; exit 1; }
command -v git >/dev/null && [ -x "$PY" ] && ok "git and python3" || { bad "git and python3 are missing: run xcode-select --install"; exit 1; }
command -v docker >/dev/null || { bad "docker is missing: install Docker Desktop (or another container runtime with the docker command)"; exit 1; }
docker info >/dev/null 2>&1 && ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?')" || { bad "docker is installed but its daemon does not answer: start Docker and run setup.sh again"; exit 1; }
node_ok && ok "Node $("$NODE_DIR/node" -v) (builds the board)" || { bad "Node 22 or newer is missing: install it from https://nodejs.org"; exit 1; }
export PATH="$NODE_DIR:$PATH"
crew_up || { bad "Kiro Crew is not running: open it, sign in, and run setup.sh again"; exit 1; }
ver="$("$KC" GET /api/version 2>/dev/null)" || {
  bad "Kiro Crew answers, but its API refused this shell as the dashboard owner: run setup.sh in your own terminal, not from an agent's shell"
  exit 1
}
v="$(printf '%s' "$ver" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
ok "Kiro Crew ${v:-?}"

step 2/5 "Build the app and install it into Kiro Crew"
echo "  This adds the app $APP to Kiro Crew's trusted apps (for this one app only), so that Kiro Crew runs it."
installed() { "$KC" GET "/api/apps/$APP" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if isinstance(d, dict) and d.get("name") else 1)' 2>/dev/null; }
if [ "$DRY" = 1 ]; then
  installed && echo "   (dry run) would update the app $APP in place" || echo "   (dry run) would build the board and install the app $APP"
  echo "   (dry run) would ask whether the sessions the app opens may auto-approve their tool calls"
  echo "   (dry run) would record this folder in $APP_DATA/data/sample.json"
else
  installed || state add created app
  if [ -z "$CONSENT" ]; then
    echo "  Each role on the team is a Kiro Crew chat session that this app opens. For the team to work on its own,"
    echo "  the app sets ${B}the sessions it opens itself${N} to auto-approve their tool calls (file edits and shell commands)."
    echo "  Other Kiro Crew sessions are not changed. The agents' shell can then also reach the emulated target through"
    echo "  Docker and write the bench state, without the operator console (see \"Guardrails\" in README.md). Use a machine"
    echo "  and user account ${B}without production credentials or customer data${N}. If you answer no, every tool call"
    echo "  waits for you to approve it in Kiro Crew."
    ask "Allow it? Type y and press Return (Return alone = no):" && CONSENT="--consent-session-approval"
  fi
  out="$(cd "$ROOT/app" && NODE_BIN="$NODE_DIR" scripts/dev-install.sh --no-test $CONSENT 2>&1)" || true
  echo "$out" | tail -4 | sed 's/^/     /'
  if echo "$out" | grep -q '"started": true'; then ok "app installed: Kiro Crew sidebar -> Apps -> $APP_LABEL"; else
    bad "the app is not running"
    echo "$out" | grep -q -e app_execution_denied -e trust_setting_overlay_owned && \
      echo "     Kiro Crew runs only trusted third-party apps: add $APP to the trusted apps in Kiro Crew's settings, then run setup.sh again."
    [ -z "$CONSENT" ] && echo "     Without consent the first enable waits for you: Kiro Crew sidebar -> Apps -> $APP_LABEL -> Enable."
    exit 1
  fi
  # the app finds checks/, bench/, knowledge/ and reference-project/ here (app/backend/team/paths.py)
  [ -e "$APP_DATA/data/sample.json" ] || state add created sample_record
  mkdir -p "$APP_DATA/data"
  "$PY" -c 'import json,sys; open(sys.argv[1], "w").write(json.dumps({"sample": sys.argv[2]}) + "\n")' "$APP_DATA/data/sample.json" "$ROOT"
  ok "scenario folder recorded for the app: $ROOT"
fi

step 3/5 "The team: knowledge and agent templates"
TEAM_ARGS=""; [ "$DRY" = 1 ] && TEAM_ARGS=--dry-run
if ! bash "$ROOT/scripts/install-team.sh" ${TEAM_ARGS:+"$TEAM_ARGS"} 2>&1 | sed 's/^/     /'; then
  bad "the team is not installed"; exit 1
fi
[ "$DRY" = 1 ] || ok "team installed"

step 4/5 "Wait for the knowledge base to be indexed"
if [ "$DRY" = 1 ]; then echo "   (dry run) would wait until Kiro Crew has indexed $TEAM_HOME/knowledge"; else
  want="$(find "$TEAM_HOME/knowledge" -type f ! -name .DS_Store | wc -l | tr -d ' ')"
  for i in $(seq 1 60); do
    set -- $(kb_state "$KNOWLEDGE")
    # Kiro Crew skips file types it does not index (the folder holds $want files), so trust its own count once synced
    if [ "$1" = synced ] && [ "$3" -gt 0 ] && [ "$2" = "$3" ]; then ok "knowledge source $KNOWLEDGE: $2 of $want files indexed"; break; fi
    [ "$i" = 60 ] && { warn "still indexing ($1, $2 of $want): wait for Knowledge -> Sources to show it synced before the first run"; break; }
    printf "     indexing (%s, %s of %s)...\r" "$1" "$2" "$want"; sleep 10
  done
fi

step 5/5 "The build container and the bench (not built by setup.sh)"
case "$(uname -m)" in arm64|aarch64) ARCH=arm64 ;; *) ARCH=amd64 ;; esac  # the build container is native (ThreadSanitizer)
echo "  The checks run in a build container and the bench is an emulated CC-1. Build them once, from this folder:"
echo "    docker build --platform linux/$ARCH -t vstatd-build:$ARCH reference-project/tools/   # the checks' build container"
echo "    bench/build-target.sh        # target image and sysroot (Buildroot; the first build took about 40 min, bench/README.md)"
echo "    bench/doctor.sh              # what is still missing"
echo "  Then: open the operator console in a terminal of its own (python3 bench/console.py), start the target"
echo "  (bench/cc1.sh start && bench/cc1.sh wait), deploy the current release (bench/cc1.sh deploy <stripped vstatd>) and"
echo "  write the baseline once: bench/cc1.sh replay --kind baseline --out $RUNS/baseline (bench/README.md)."
echo "  Until the bench is ready a run stops before its first bench action, and the board says what is missing."

echo
if [ "$DRY" = 1 ]; then echo "${B}Dry run: nothing was changed.${N}"; else
  echo "${B}Done.${N} Open Kiro Crew -> Apps -> $APP_LABEL -> 团队看板, and start a run with 新需求 (see README.md)."
fi
