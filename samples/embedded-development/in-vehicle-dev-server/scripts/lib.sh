# shellcheck shell=bash disable=SC2034  # the names below are used by the scripts that source this file
# Shared by setup.sh, cleanup.sh and install-team.sh (adapted from the agent-team sample's scripts/lib.sh). Source it
# after setting ROOT to this scenario's folder.
#
# For tests only: VSTATD_KCAPI replaces app/scripts/kcapi.sh (Kiro Crew's health is then asked through it too) and
# VSTATD_INSTALL_STATE replaces .install-state.json (scripts/state.py). VSTATD_KIROCREW_BIN names the kirocrew program
# (kirocrew_bin below), for a test or a kirocrew setup.sh does not find.
ROOT="${ROOT:?}"
KC="${VSTATD_KCAPI:-$ROOT/app/scripts/kcapi.sh}"   # calls the local Kiro Crew API as the dashboard owner
# the gateway's loopback port, exported so that kcapi.sh in a child process reads the same one: set as a shell
# variable alone it would leave the health check and the API calls on two different ports
export KC_PORT="${KC_PORT:-5476}"
PY=/usr/bin/python3
export PYTHONDONTWRITEBYTECODE=1   # scripts/templates.py imports state.py: no __pycache__ left in scripts/
B=$'\033[1m'; G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; N=$'\033[0m'

step() { echo; echo "${B}[$1] $2${N}"; }
ok()   { echo "  ${G}✓${N} $*"; }
warn() { echo "  ${Y}!${N} $*"; }
bad()  { echo "  ${R}✗${N} $*"; }
ask()  { local a; read -r -p "  $1 " a; [ "$a" = y ] || [ "$a" = Y ]; }
state() { "$PY" "$ROOT/scripts/state.py" "$@"; }   # what setup created: see scripts/state.py
# how to start Kiro Crew, for the messages: the desktop app on macOS; on Linux the desktop app or the CLI's gateway
if [ "$(uname -s)" = Linux ]; then
  CREW_START="start it (the desktop app, kirocrew gateway, or kirocrew service install)"
else CREW_START="open it"; fi

# Kiro Crew is running and answers on its loopback port
crew_up() {
  if [ -n "${VSTATD_KCAPI:-}" ]; then "$KC" GET /api/health | grep -q '"ok": *true'; return; fi
  curl -s --noproxy '*' --max-time 3 "http://127.0.0.1:${KC_PORT}/api/health" | grep -q '"ok": *true'
}

# NODE_DIR := the folder of a node 22 or newer (PATH, Homebrew, nvm)
node_ok() {
  local d v
  for d in "$(dirname "$(command -v node 2>/dev/null || echo /nonexistent/node)")" /opt/homebrew/bin /usr/local/bin \
           $(ls -d "$HOME"/.nvm/versions/node/v*/bin 2>/dev/null); do
    v="$("$d/node" -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
    [ "$v" -ge 22 ] && { NODE_DIR="$d"; return 0; }
  done
  return 1
}

# the folder of the running Kiro Crew desktop app, else /Applications/KiroCrew.app (macOS only)
crew_app_dir() {
  local app
  app="$(/bin/ps -axo command= | /usr/bin/sed -n 's#^\(/.*/KiroCrew\.app\)/Contents/MacOS/KiroCrew.*#\1#p' | /usr/bin/head -1)"
  echo "${app:-/Applications/KiroCrew.app}"
}

# The kirocrew program, by its absolute path: $VSTATD_KIROCREW_BIN, else on macOS the one in the Kiro Crew desktop app,
# else the first kirocrew on PATH (on Linux: the desktop app's, or the CLI's in pipx or ~/.kiro/crew-venv). Absolute,
# because the templates name it and a gateway run as a systemd service may not have this shell's PATH.
kirocrew_bin() {
  local p="${VSTATD_KIROCREW_BIN:-}" arch
  if [ -z "$p" ]; then
    if [ "$(uname -s)" = Darwin ]; then
      arch="$([ "$(uname -m)" = arm64 ] && echo arm64 || echo x64)"
      p="$(crew_app_dir)/Contents/Resources/backend-dist/kirocrew-backend-$arch/bin/kirocrew"
    fi
    [ -n "$p" ] && [ -f "$p" ] && [ -x "$p" ] || p="$(command -v kirocrew 2>/dev/null || true)"
  fi
  if [ -z "$p" ] || [ ! -f "$p" ] || [ ! -x "$p" ]; then
    bad "cannot find the kirocrew program${p:+ at $p}: install Kiro Crew (the desktop app or its CLI," \
      "https://kiro.dev/docs/crew/installation), or set VSTATD_KIROCREW_BIN to the kirocrew program" >&2
    return 1
  fi
  case "$p" in /*) ;; *) p="$(cd "$(dirname "$p")" && pwd -P)/$(basename "$p")" ;; esac  # a relative PATH entry
  echo "$p"
}

# GET <path> lists <list key> with an item whose <field> is <value>
has() {
  "$KC" GET "$1" | "$PY" -c "import json,sys; d=json.load(sys.stdin); items=d.get(sys.argv[1], d) if isinstance(d, dict) else d; sys.exit(0 if any(str(x.get(sys.argv[2]))==sys.argv[3] for x in items) else 1)" "$2" "$3" "$4"
}

# The app is installed in Kiro Crew: exit 0 when it is, 1 when Kiro Crew says it is not (404), 3 when Kiro Crew did not
# answer that way (an error, no answer, or this shell is not the dashboard owner)
installed() {
  local code
  code="$("$KC" --status GET "/api/apps/$APP" 2>/dev/null)" || return 3
  case "$code" in 200) return 0 ;; 404) return 1 ;; *) return 3 ;; esac
}

# The app is on Kiro Crew's list of trusted apps, in effect or stored but not in effect (both can be revoked): exit 0
# when it is, 1 when the list does not have it, 3 when Kiro Crew did not list them
trusted() {
  local rc=0
  "$KC" GET /api/security/trusted-apps 2>/dev/null | "$PY" -c 'import json,sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(3)
if not isinstance(d, dict) or not all(isinstance(d.get(k, []), list) for k in ("apps", "ineffective")) \
        or "apps" not in d:
    sys.exit(3)
sys.exit(0 if sys.argv[1] in d["apps"] + d.get("ineffective", []) else 1)' "$APP" 2>/dev/null || rc=$?
  return "$rc"
}

# knowledge source <name>: "<sync_status> <files_done> <files_total>", or "absent 0 0"
kb_state() {
  "$KC" GET /api/knowledge/sources | "$PY" -c "import json,sys; d=json.load(sys.stdin); rows=d.get('sources',d) if isinstance(d,dict) else d; r=[x for x in rows if x.get('name')==sys.argv[1]]; sp=(r[0].get('spend') or {}) if r else {}; print(r[0].get('sync_status') if r else 'absent', sp.get('files_done') or 0, sp.get('files_total') or 0)" "$1" 2>/dev/null || echo "unknown 0 0"
}

# The app, the team and their names in Kiro Crew and on disk. setup.sh creates them; cleanup.sh removes what it created.
APP=vstatd-team
APP_LABEL="AIDLC-Embedded团队"
APP_DATA="$HOME/.kiro/crew/apps/$APP"           # the installed app; its data directory (runs, sessions) is data/
RUNS="$HOME/workplace/$APP"                       # every run's repository, worktrees and results, and the baseline
TEAM_HOME="$HOME/workplace/vstatd"                # the knowledge copy the knowledge source indexes
WORKSPACE=vstatd                                  # a Kiro Crew workspace an earlier setup created; cleanup.sh removes it
KNOWLEDGE=vstatd                                  # the Kiro Crew knowledge source (the team file names it)
# The team's agent templates (agents/kiro-crew/make_templates.py). The roles' sessions run them directly, with no Kiro
# Crew member: Kiro Crew 0.12 builds a new member from its own worker, not from a template (mate_template_unsupported).
TEMPLATES=(embedded-developer-agent embedded-architect-agent embedded-quality-agent embedded-architecture-reviewer-agent)
AGENTS="$HOME/.kiro/agents"
BACKUP="$AGENTS/.vstatd-team-sample-backup"       # templates setup replaced, put back by cleanup.sh
