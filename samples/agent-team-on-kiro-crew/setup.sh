#!/usr/bin/env bash
# Install the sample into the Kiro Crew running on this Mac: bash setup.sh
#
#   bash setup.sh                               # asks once whether the app may auto-approve the sessions it opens
#   bash setup.sh --consent-session-approval    # the same, answering yes without asking
#
# Safe to re-run: what exists already is kept, the app is updated in place. What this script creates is recorded in
# .install-state.json, and cleanup.sh removes only that. Keep this folder where it is after setup: Kiro Crew installs
# the app from it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd -P)"
source "$ROOT/scripts/lib.sh"
CONSENT=""
for a in "$@"; do
  case "$a" in
    --consent-session-approval) CONSENT="--consent-session-approval" ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

step 1/4 "Prerequisites"
[ "$(uname -s)" = Darwin ] && ok "macOS $(sw_vers -productVersion) ($(uname -m))" || { bad "this sample runs on macOS"; exit 1; }
command -v git >/dev/null && [ -x "$PY" ] && ok "git and python3" || { bad "git and python3 are missing: run xcode-select --install"; exit 1; }
node_ok && ok "Node $("$NODE_DIR/node" -v)" || { bad "Node 22 or newer is missing: install it from https://nodejs.org"; exit 1; }
export PATH="$NODE_DIR:$PATH"
crew_up || { bad "Kiro Crew is not running: open it, sign in, and run setup.sh again"; exit 1; }
v="$("$KC" GET /api/version | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)"
ok "Kiro Crew ${v:-?}"

step 2/4 "Build the app and install it into Kiro Crew"
echo "  This adds the app aidlc-team to Kiro Crew's trusted apps (for this one app only), so that Kiro Crew runs it."
installed() { "$KC" GET /api/apps/aidlc-team | "$PY" -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if isinstance(d, dict) and d.get("name") else 1)' 2>/dev/null; }
installed || "$PY" "$ROOT/scripts/state.py" add created app
if [ -z "$CONSENT" ]; then
  echo "  Each role on the team is a Kiro Crew chat session that this app opens. For the team to work on its own,"
  echo "  the app sets ${B}the sessions it opens itself${N} to auto-approve their tool calls (file edits and shell commands)."
  echo "  Other Kiro Crew sessions are not changed. If you answer no, every tool call waits for you to"
  echo "  approve it in Kiro Crew. See \"Guardrails\" in README.md before you agree."
  ask "Allow it? Type y and press Return (Return alone = no):" && CONSENT="--consent-session-approval"
fi
out="$(cd "$ROOT/app" && NODE_BIN="$NODE_DIR" scripts/dev-install.sh --no-test $CONSENT 2>&1)" || true
echo "$out" | tail -4 | sed 's/^/     /'
if echo "$out" | grep -q '"started": true'; then ok "app installed: Kiro Crew sidebar -> Apps -> AI-DLC 多 Agent 团队"; else
  bad "the app is not running"
  echo "$out" | grep -q -e app_execution_denied -e trust_setting_overlay_owned && \
    echo "     Kiro Crew runs only trusted third-party apps: add aidlc-team to the trusted apps in Kiro Crew's settings, then run setup.sh again."
  [ -z "$CONSENT" ] && echo "     Without consent the first enable waits for you: Kiro Crew sidebar -> Apps -> AI-DLC 多 Agent 团队 -> Enable."
  exit 1
fi

step 3/4 "Example company: knowledge base, data and team members"
bash "$ROOT/scripts/install-example-company.sh" 2>&1 | sed 's/^/     /'
ok "example company installed"

step 4/4 "Wait for the knowledge base to be indexed (about 5 minutes)"
want="$(find "$COMPANY_HOME/knowledge" -type f ! -name .DS_Store | wc -l | tr -d ' ')"
for i in $(seq 1 60); do
  set -- $(kb_state "$KNOWLEDGE")
  # Kiro Crew counts files as it finds them: wait until it has at least as many as the folder holds
  if [ "$1" = synced ] && [ "$2" -ge "$want" ] && [ "$2" = "$3" ]; then ok "knowledge source $KNOWLEDGE: $2 documents indexed"; break; fi
  [ "$i" = 60 ] && { warn "still indexing ($1, $2 of $want): wait for Knowledge -> Sources to show it synced before the first run"; break; }
  printf "     indexing (%s, %s of %s)...\r" "$1" "$2" "$want"; sleep 10
done

echo
echo "${B}Done.${N} Open Kiro Crew -> Apps -> AI-DLC 多 Agent 团队 -> 团队看板, and start a run with 新需求 (see README.md)."
