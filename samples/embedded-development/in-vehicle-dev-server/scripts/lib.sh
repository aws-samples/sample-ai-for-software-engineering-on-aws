# shellcheck shell=bash disable=SC2034  # the names below are used by the scripts that source this file
# Shared by setup.sh, cleanup.sh and install-team.sh (adapted from the agent-team sample's scripts/lib.sh). Source it
# after setting ROOT to this scenario's folder.
#
# For tests only: VSTATD_KCAPI replaces app/scripts/kcapi.sh (Kiro Crew's health is then asked through it too),
# VSTATD_INSTALL_STATE replaces .install-state.json (scripts/state.py) and VSTATD_KIROCREW_BIN the kirocrew program the
# templates name (scripts/install-team.sh).
ROOT="${ROOT:?}"
KC="${VSTATD_KCAPI:-$ROOT/app/scripts/kcapi.sh}"   # calls the local Kiro Crew API as the dashboard owner
PY=/usr/bin/python3
B=$'\033[1m'; G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; N=$'\033[0m'

step() { echo; echo "${B}[$1] $2${N}"; }
ok()   { echo "  ${G}✓${N} $*"; }
warn() { echo "  ${Y}!${N} $*"; }
bad()  { echo "  ${R}✗${N} $*"; }
ask()  { local a; read -r -p "  $1 " a; [ "$a" = y ] || [ "$a" = Y ]; }
state() { "$PY" "$ROOT/scripts/state.py" "$@"; }   # what setup created: see scripts/state.py

# Kiro Crew is running and answers on its loopback port
crew_up() {
  if [ -n "${VSTATD_KCAPI:-}" ]; then "$KC" GET /api/health | grep -q '"ok": *true'; return; fi
  curl -s --noproxy '*' --max-time 3 http://127.0.0.1:5476/api/health | grep -q '"ok": *true'
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

# the folder of the running Kiro Crew desktop app, else /Applications/KiroCrew.app
crew_app_dir() {
  local app
  app="$(/bin/ps -axo command= | /usr/bin/sed -n 's#^\(/.*/KiroCrew\.app\)/Contents/MacOS/KiroCrew.*#\1#p' | /usr/bin/head -1)"
  echo "${app:-/Applications/KiroCrew.app}"
}

# GET <path> lists <list key> with an item whose <field> is <value>
has() {
  "$KC" GET "$1" | "$PY" -c "import json,sys; d=json.load(sys.stdin); items=d.get(sys.argv[1], d) if isinstance(d, dict) else d; sys.exit(0 if any(str(x.get(sys.argv[2]))==sys.argv[3] for x in items) else 1)" "$2" "$3" "$4"
}

# knowledge source <name>: "<sync_status> <files_done> <files_total>", or "absent 0 0"
kb_state() {
  "$KC" GET /api/knowledge/sources | "$PY" -c "import json,sys; d=json.load(sys.stdin); rows=d.get('sources',d) if isinstance(d,dict) else d; r=[x for x in rows if x.get('name')==sys.argv[1]]; sp=(r[0].get('spend') or {}) if r else {}; print(r[0].get('sync_status') if r else 'absent', sp.get('files_done') or 0, sp.get('files_total') or 0)" "$1" 2>/dev/null || echo "unknown 0 0"
}

# The app, the team and their names in Kiro Crew and on disk. setup.sh creates them; cleanup.sh removes what it created.
APP=vstatd-team
APP_LABEL="车载平台服务 · AI-DLC 团队"
APP_DATA="$HOME/.kiro/crew/apps/$APP"           # the installed app; its data directory (runs, sessions) is data/
RUNS="$HOME/workplace/$APP"                       # every run's repository, worktrees and results, and the baseline
TEAM_HOME="$HOME/workplace/vstatd"                # the knowledge copy the knowledge source indexes
WORKSPACE=vstatd                                  # the Kiro Crew workspace of the team's members
KNOWLEDGE=vstatd                                  # the Kiro Crew knowledge source (the team file names it)
MEMBERS=(embedded-developer embedded-architect embedded-quality embedded-architecture-reviewer)
AGENTS="$HOME/.kiro/agents"
BACKUP="$AGENTS/.vstatd-team-sample-backup"       # templates setup replaced, put back by cleanup.sh
