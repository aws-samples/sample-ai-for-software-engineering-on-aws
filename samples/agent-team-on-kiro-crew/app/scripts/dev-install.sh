#!/usr/bin/env bash
# Install or update aidlc-team into the LOCAL running KiroCrew gateway, grant narrow per-app trust, enable it,
# and print hook health. Idempotent: re-run after every change.
#
#   scripts/dev-install.sh             # check + build UI, install-or-update, trust, enable, health
#   scripts/dev-install.sh --no-test   # skip the UI type check and tests
#   scripts/dev-install.sh --no-build  # skip the UI build
#   scripts/dev-install.sh --dev       # also turn on dev mode
#   scripts/dev-install.sh --consent-session-approval  # first enable after asking for sessionApproval
#
# sessionApproval: app.json asks for `permissions.sessionApproval` so the app may set its OWN role
# sessions to trust (POST /api/chat/mode with a slot). KiroCrew grants it only with the dashboard
# owner's consent, normally in the enable dialog; the flag sends that consent as the owner instead.
# Later disable/update/enable cycles keep it.
#
# Backend hooks are only re-imported on enable, so this always disables before updating, and it NEVER
# uninstalls (an uninstall drops the app's trust grant).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd -P)"  # physical path: KiroCrew records it as the install source
APP="aidlc-team"
KCAPI="$ROOT/scripts/kcapi.sh"
# node's folder: $NODE_BIN, else the first node 22+ on PATH, Homebrew (Apple or Intel), or nvm (newest first)
node_ok() { [ -x "$1/node" ] && [ "$("$1/node" -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)" -ge 22 ]; }
if [ -z "${NODE_BIN:-}" ]; then
  for d in "$(dirname "$(command -v node 2>/dev/null || echo /nonexistent/node)")" /opt/homebrew/bin /usr/local/bin \
           $(ls -d "$HOME"/.nvm/versions/node/v*/bin 2>/dev/null | sort -t v -k 2 -V -r); do
    node_ok "$d" && { NODE_BIN="$d"; break; }
  done
fi
[ -n "${NODE_BIN:-}" ] && node_ok "$NODE_BIN" || { echo "!! need node 22 or newer: install it, or pass NODE_BIN=<folder of node>" >&2; exit 1; }
export PATH="$NODE_BIN:$PATH"
PY3=/usr/bin/python3
BUILD=1; TEST=1; DEV=0; CONSENT=0
for a in "$@"; do
  case "$a" in
    --no-build) BUILD=0 ;;
    --no-test) TEST=0 ;;
    --dev) DEV=1 ;;
    --consent-session-approval) CONSENT=1 ;;
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

# A fresh clone has no ui/node_modules: install them from the lockfile (registry.npmjs.org), or, with no network,
# use a ui/dist that is already built.
if [ "$BUILD" = 1 ] && [ ! -d "$ROOT/ui/node_modules/vite" ]; then
  if [ -L "$ROOT/ui/node_modules" ] && [ ! -e "$ROOT/ui/node_modules" ]; then rm "$ROOT/ui/node_modules"; fi
  echo "== installing UI dependencies (npm ci)"
  if ! (cd "$ROOT/ui" && "$NODE_BIN/npm" ci --no-audit --no-fund --silent); then
    [ -f "$ROOT/ui/dist/index.mjs" ] || { echo "!! npm ci failed and there is no ui/dist to fall back on" >&2; exit 1; }
    echo "   npm ci failed: installing the ui/dist that is already built"
    BUILD=0
  fi
fi

if [ "$BUILD" = 1 ] && [ -f "$ROOT/ui/package.json" ]; then
  if [ "$TEST" = 1 ]; then
    # A page that fails its own checks is not installed.
    echo "== checking UI (tsc + vitest; --no-test skips)"
    (cd "$ROOT/ui" && "$NODE_BIN/npm" run typecheck --silent && "$NODE_BIN/npm" run test --silent)
  fi
  echo "== building UI"
  (cd "$ROOT/ui" && "$NODE_BIN/npm" run build --silent)
  "$NODE_BIN/node" --check "$ROOT/ui/dist/index.mjs"
  # React comes from the host's import map: a second copy in the bundle breaks every hook.
  if grep -q -e '__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED' -e 'react-dom.production' "$ROOT/ui/dist/index.mjs"; then
    echo "!! ui/dist/index.mjs contains React's own code: keep react / react-dom external in vite.config.ts" >&2
    exit 1
  fi
fi

echo "== install or update"
installed=$("$KCAPI" GET "/api/apps/${APP}" | $PY3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("no"); raise SystemExit
print("yes" if isinstance(d, dict) and d.get("name") else "no")' 2>/dev/null || echo no)
if [ "$installed" = "yes" ]; then
  "$KCAPI" POST "/api/apps/${APP}/disable" '{}' >/dev/null || true
  "$KCAPI" POST "/api/apps/${APP}/update" "{\"source\":\"${ROOT}\"}"
else
  "$KCAPI" POST "/api/apps/install" "{\"source\":\"${ROOT}\"}"
fi

echo "== trust (narrow, per-app)"
"$KCAPI" POST "/api/security/trusted-apps/${APP}" '{}' || true

echo "== enable"
if [ "$CONSENT" = 1 ]; then
  echo "   (sending sessionApprovalConsent as the dashboard owner)"
  out=$("$KCAPI" POST "/api/apps/${APP}/enable" '{"sessionApprovalConsent": true}')
else
  out=$("$KCAPI" POST "/api/apps/${APP}/enable" '{}')
fi
echo "$out" | $PY3 -c 'import json,sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    print(raw); raise SystemExit
keep = {k: d.get(k) for k in ("ok", "name", "message", "error", "code", "error_code") if k in d}
hooks = d.get("hooks") or {}
if hooks:
    keep["hooks"] = {k: hooks.get(k) for k in ("hooks_routes_count", "hooks_startup", "health_status") if k in hooks}
    if "hooks_routes" in hooks:
        keep["hooks"]["routes"] = len(hooks["hooks_routes"])
print(json.dumps(keep, ensure_ascii=False))
if "session_approval_consent_required" in raw:
    print("!! first enable needs owner consent for permissions.sessionApproval:"
          " click Enable on the app in the dashboard, or re-run with --consent-session-approval")
'

if [ "$DEV" = 1 ]; then
  echo "== dev mode"
  "$KCAPI" POST "/api/apps/${APP}/dev" '{"enabled":true}'
fi

echo "== hook health"
"$KCAPI" GET "/api/apps" | APP="$APP" $PY3 -c '
import json, os, sys
apps = json.load(sys.stdin)
apps = apps if isinstance(apps, list) else apps.get("apps", [])
want = os.environ["APP"]
for a in apps:
    if a.get("name") == want:
        print(json.dumps({k: a.get(k) for k in ("name", "version", "enabled", "hooks", "backend_status")}, indent=1, ensure_ascii=False))
'
echo "== app health"
sleep 2
"$KCAPI" GET "/api/apps/${APP}/health"
