#!/usr/bin/env bash
# Call the LOCAL KiroCrew gateway API as the dashboard owner.
#
#   scripts/kcapi.sh GET  /api/apps
#   scripts/kcapi.sh POST /api/apps/aidlc-team/route '{"requirement":"双十一大促"}'
#   scripts/kcapi.sh GET  /api/apps/aidlc-team/health
#
# Auth: `kirocrew token`, run with the gateway's OWN interpreter, mints a 5-minute link token signed with
# ~/.kiro/crew/token_signing.key; the first request carrying `?token=` exchanges it for the HttpOnly session
# cookie, which is cached in a jar and reused. The gateway has no `Authorization: Bearer` support: cookies are
# the contract. KC_BASE defaults to the loopback address the gateway listens on.
set -euo pipefail

CURL=/usr/bin/curl
GREP=/usr/bin/grep
HEAD=/usr/bin/head
PY3=/usr/bin/python3

KC_PORT="${KC_PORT:-5476}"
KC_BASE="${KC_BASE:-http://127.0.0.1:${KC_PORT}}"
# The session cookie is the dashboard owner's: keep it in the per-user temp folder, readable by this user only
umask 077
KC_JAR="${KC_JAR:-${TMPDIR:-/tmp}/kc-cookies-${KC_PORT}.jar}"
if [ -z "${KC_PY:-}" ]; then  # the gateway's own interpreter: the running app's, else the one in /Applications
  RUNNING_APP="$(/bin/ps -axo command= | /usr/bin/sed -n 's#^\(/.*/KiroCrew\.app\)/Contents/MacOS/KiroCrew.*#\1#p' | $HEAD -1)"
  for p in ${RUNNING_APP:+"$RUNNING_APP"/Contents/Resources/backend-dist/kirocrew-backend-*/bin/python3.12} \
           /Applications/KiroCrew.app/Contents/Resources/backend-dist/kirocrew-backend-*/bin/python3.12; do
    [ -x "$p" ] && "$p" -c 'import kiro_crew' 2>/dev/null && { KC_PY="$p"; break; }
  done
fi

usage() { echo "usage: $(basename "$0") <METHOD> <PATH> [JSON_BODY]" >&2; exit 2; }
[ $# -ge 2 ] || usage
METHOD="$1"; PATH_="$2"; BODY="${3:-}"

session_ok() { $CURL --noproxy '*' -s -f -b "$KC_JAR" "${KC_BASE}/api/auth/me" >/dev/null 2>&1; }

mint() {
  local url token
  url=$("$KC_PY" -m kiro_crew token 2>/dev/null | $GREP -o 'token=.*' | $HEAD -1) || true
  token="${url#token=}"
  if [ -z "$token" ]; then
    echo "kcapi: could not mint a token — is the gateway running on ${KC_PORT}?" >&2
    exit 1
  fi
  $CURL --noproxy '*' -s -o /dev/null -c "$KC_JAR" "${KC_BASE}/?token=${token}"
  session_ok || { echo "kcapi: cookie exchange failed" >&2; exit 1; }
}

# The cookie jar is reused as is: asking /api/auth/me before every call would double the security-event rows
# each call writes. A lapsed or missing session answers 401, or 403
# "Token required": mint once and retry; any other answer is the call's own.
OUT=$(/usr/bin/mktemp "${TMPDIR:-/tmp}/kcapi.XXXXXX")
trap '/bin/rm -f "$OUT"' EXIT

call() {
  if [ -n "$BODY" ]; then
    $CURL --noproxy '*' -s -o "$OUT" -w '%{http_code}' -b "$KC_JAR" -c "$KC_JAR" -X "$METHOD" -H 'Content-Type: application/json' -d "$BODY" "${KC_BASE}${PATH_}"
  else
    $CURL --noproxy '*' -s -o "$OUT" -w '%{http_code}' -b "$KC_JAR" -c "$KC_JAR" -X "$METHOD" "${KC_BASE}${PATH_}"
  fi
}

[ -s "$KC_JAR" ] || mint
code=$(call) || code=000
if [ "$code" = "401" ] || { [ "$code" = "403" ] && $GREP -q '"Token required"' "$OUT"; }; then
  mint
  code=$(call) || code=000
fi
/bin/cat "$OUT"
echo
