# Shared by setup.sh, cleanup.sh and install-example.sh. Source it after setting ROOT to the sample folder.
ROOT="${ROOT:?}"
KC="$ROOT/app/scripts/kcapi.sh"   # calls the local Kiro Crew API as the dashboard owner
PY=/usr/bin/python3
B=$'\033[1m'; G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; N=$'\033[0m'

step() { echo; echo "${B}[$1] $2${N}"; }
ok()   { echo "  ${G}✓${N} $*"; }
warn() { echo "  ${Y}!${N} $*"; }
bad()  { echo "  ${R}✗${N} $*"; }
ask()  { local a; read -r -p "  $1 " a; [ "$a" = y ] || [ "$a" = Y ]; }

# Kiro Crew is running and answers on its loopback port
crew_up() { curl -s --noproxy '*' --max-time 3 http://127.0.0.1:5476/api/health | grep -q '"ok": *true'; }

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

# a Kiro Crew member (Customize -> Teammates) with this name exists
member_present() {
  "$KC" GET /api/agents | "$PY" -c "import json,sys; d=json.load(sys.stdin); rows=d.get('agents', d) if isinstance(d,dict) else d; sys.exit(0 if any(r.get('name')==sys.argv[1] for r in rows) else 1)" "$1"
}

# knowledge source <name>: "<sync_status> <files_done> <files_total>", or "absent 0 0"
kb_state() {
  "$KC" GET /api/knowledge/sources | "$PY" -c "import json,sys; d=json.load(sys.stdin); rows=d.get('sources',d) if isinstance(d,dict) else d; r=[x for x in rows if x.get('name')==sys.argv[1]]; sp=(r[0].get('spend') or {}) if r else {}; print(r[0].get('sync_status') if r else 'absent', sp.get('files_done') or 0, sp.get('files_total') or 0)" "$1" 2>/dev/null || echo "unknown 0 0"
}

# The example's names in Kiro Crew and on disk. install-example.sh creates them; cleanup.sh removes what it created.
COMPANY_HOME="$HOME/workplace/taoyuan"   # knowledge files and data the agents read
WORKSPACE=taoyuan                         # the Kiro Crew workspace of the team's members
KNOWLEDGE=桃源科技                          # the Kiro Crew knowledge source (the team files name it)
MEMBERS=(aidlc-product-agent aidlc-product-lead-agent aidlc-architect-agent aidlc-architecture-reviewer-agent
         aidlc-design-agent aidlc-developer-agent aidlc-quality-agent aidlc-devsecops-agent aidlc-compliance-agent
         aidlc-pipeline-deploy-agent aidlc-aws-platform-agent aidlc-operations-agent aidlc-delivery-agent
         aidlc-composer-agent taoyuan-motion-agent)
