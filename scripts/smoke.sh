#!/usr/bin/env bash
# End-to-end smoke test against a RUNNING stack (`make up && make seed` first).
#
#   bash scripts/smoke.sh          # REST: the five demo scenarios, end to end   (make smoke)
#   bash scripts/smoke.sh mcp      # MCP: initialize -> tools/list -> whoami      (make mcp-smoke)
#
# Env: BASE (default http://localhost:8000), MCP_URL (default $BASE/mcp/).
# Prints one line per step (HTTP status + summary) and exits non-zero on the first failure.
# Note: the REST run revokes the board-deck `leadership` grant (scenario 4). Re-running restores
# it first, so the script is repeatable; `make seed` also restores it.
set -euo pipefail

BASE=${BASE:-http://localhost:8000}
MCP_URL=${MCP_URL:-$BASE/mcp/}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

for bin in curl jq; do
  command -v "$bin" >/dev/null 2>&1 || {
    echo "smoke: '$bin' is required" >&2
    exit 2
  }
done

STEP=0
CODE=000
NONEXISTENT_ID=00000000-0000-4000-8000-000000000000
DECK_SLUG=files/board-deck-q3
RUNBOOK_SLUG=runbooks/payment-rail-failover

step() {
  STEP=$((STEP + 1))
  printf '%2d. %-46s ' "$STEP" "$1"
}
ok() { printf '%s  %s\n' "$CODE" "$1"; }
fail() {
  printf '%s  FAIL: %s\n' "$CODE" "$1"
  echo "---- response body ----"
  cat "$TMP/body" 2>/dev/null || true
  echo
  exit 1
}
expect() { [[ "$CODE" == "$1" ]] || fail "expected HTTP $1"; }
expect_2xx() { [[ "$CODE" =~ ^2[0-9][0-9]$ ]] || fail "expected HTTP 2xx"; }
body() { cat "$TMP/body"; }

# call METHOD PATH ACTOR [extra curl args...]   -> sets CODE; response body in $TMP/body
call() {
  local method=$1 path=$2 actor=$3
  shift 3
  local args=(-sS -o "$TMP/body" -w '%{http_code}' -X "$method")
  if [[ -n "$actor" ]]; then args+=(-H "X-Actor-Id: $actor"); fi
  CODE=$(curl "${args[@]}" "$@" "$BASE$path") || {
    CODE=000
    fail "curl could not reach $BASE$path"
  }
}

# ask ACTOR QUESTION   -> POST /api/ask
ask() {
  local payload
  payload=$(jq -n --arg q "$2" '{question: $q}')
  call POST /api/ask "$1" -H 'Content-Type: application/json' -d "$payload"
}

# ---------------------------------------------------------------------------------------------
# MCP mode
# ---------------------------------------------------------------------------------------------

# Streamable HTTP may answer with JSON or with an SSE stream; normalise to the last JSON message.
mcp_json() {
  if grep -q '^data:' "$TMP/body"; then
    grep '^data:' "$TMP/body" | sed 's/^data: \{0,1\}//' | tail -n 1
  else
    cat "$TMP/body"
  fi
}

# mcp_post JSON [extra curl args...]   -> sets CODE; headers in $TMP/headers
mcp_post() {
  local payload=$1
  shift
  CODE=$(curl -sS -L -o "$TMP/body" -D "$TMP/headers" -w '%{http_code}' -X POST \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    -H 'X-Actor-Id: alex.tan' \
    "$@" -d "$payload" "$MCP_URL") || {
    CODE=000
    fail "curl could not reach $MCP_URL"
  }
}

run_mcp() {
  echo "MCP smoke against $MCP_URL"
  local session="" proto="2025-06-18" extra=()

  step "initialize (as alex.tan)"
  mcp_post '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke.sh","version":"1.0"}}}'
  expect 200
  mcp_json >"$TMP/msg"
  jq -e '.result.serverInfo' "$TMP/msg" >/dev/null 2>&1 || fail "no result.serverInfo in initialize"
  session=$(grep -i '^mcp-session-id:' "$TMP/headers" | tail -n 1 | cut -d: -f2- | tr -d ' \r' || true)
  proto=$(jq -r '.result.protocolVersion // "2025-06-18"' "$TMP/msg")
  if [[ -n "$session" ]]; then extra+=(-H "mcp-session-id: $session"); fi
  extra+=(-H "mcp-protocol-version: $proto")
  ok "server=$(jq -r '.result.serverInfo.name' "$TMP/msg") protocol=$proto session=${session:-<stateless>}"

  step "notifications/initialized"
  mcp_post '{"jsonrpc":"2.0","method":"notifications/initialized"}' "${extra[@]}"
  expect_2xx
  ok "acknowledged"

  step "tools/list"
  mcp_post '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' "${extra[@]}"
  expect 200
  mcp_json >"$TMP/msg"
  jq -e '.result.tools | length > 0' "$TMP/msg" >/dev/null 2>&1 || fail "no tools listed"
  jq -e '[.result.tools[].name] | index("query") != null' "$TMP/msg" >/dev/null 2>&1 ||
    fail "tool 'query' missing"
  ok "$(jq -r '.result.tools | length' "$TMP/msg") tools"
  jq -r '.result.tools[].name' "$TMP/msg" | sort | sed 's/^/      - /'

  step "tools/call whoami"
  mcp_post '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"whoami","arguments":{}}}' "${extra[@]}"
  expect 200
  mcp_json >"$TMP/msg"
  jq -e '.result.isError != true' "$TMP/msg" >/dev/null 2>&1 || fail "whoami returned an error"
  ok "$(jq -r '.result.content[0].text // "" | .[0:100]' "$TMP/msg")"

  echo "MCP smoke passed."
}

# ---------------------------------------------------------------------------------------------
# REST mode: the five demo scenarios
# ---------------------------------------------------------------------------------------------
run_rest() {
  echo "REST smoke against $BASE"

  step "GET /healthz"
  call GET /healthz ""
  expect 200
  ok "$(jq -r '"status=\(.status) db=\(.db) redis=\(.redis) provider_mode=\(.provider_mode)"' "$TMP/body")"

  step "GET /api/principals"
  call GET /api/principals ""
  expect 200
  jq -e '[.items[].id] | index("john.tan") != null' "$TMP/body" >/dev/null 2>&1 ||
    fail "seeded personas missing (run make seed)"
  ok "$(jq -r '[.items[].id] | join(", ")' "$TMP/body")"

  step "POST /api/documents/upload (alex.tan)"
  cat >"$TMP/smoke-note.md" <<'MD'
# Smoke test note

Uploaded by scripts/smoke.sh to prove the upload -> ingest path. Synthetic content only.
MD
  call POST /api/documents/upload alex.tan -F "file=@$TMP/smoke-note.md;type=text/markdown"
  expect 201
  ok "document=$(jq -r '.document.id' "$TMP/body") ingest=$(jq -r '.ingest.status // "?"' "$TMP/body")"

  step "ask: failover procedure (john.tan)"
  ask john.tan "What is the payment rail failover procedure?"
  expect 200
  jq -e --arg s "$RUNBOOK_SLUG" '[.citations[] | select(.slug == $s)] | length == 0' "$TMP/body" \
    >/dev/null 2>&1 || fail "stale critical runbook was cited (scenario 2)"
  jq -e --arg s "$RUNBOOK_SLUG" \
    '[.freshness_receipt.evidence_items[]? | select(.page_slug == $s and .safe_to_use == false)] | length > 0' \
    "$TMP/body" >/dev/null 2>&1 || fail "receipt does not mark the failover runbook unsafe (scenario 2)"
  ok "$(jq -r '"citations=\(.citations | length) abstained=\(.answer.abstained) receipt=\(.freshness_receipt.overall_status) runbook=\([.freshness_receipt.evidence_items[] | select(.page_slug == "runbooks/payment-rail-failover") | .freshness_status][0])"' "$TMP/body")"

  step "find board deck (root.admin)"
  call GET "/api/documents?source_id=gdrive-finance&limit=100" root.admin
  expect 200
  local deck_id
  deck_id=$(jq -r --arg s "$DECK_SLUG" '[.items[] | select(.slug == $s) | .id][0] // empty' "$TMP/body")
  [[ -n "$deck_id" ]] || fail "board deck not found (run make seed)"
  ok "deck=$deck_id"

  step "list grants for board deck (root.admin)"
  call GET "/api/access/grants?document_id=$deck_id" root.admin
  expect 200
  local grant_id
  grant_id=$(jq -r '[.items[] | select(.subject_type == "group" and .subject_id == "leadership"
      and .effect == "allow" and .revoked_at == null) | .id][0] // empty' "$TMP/body")
  if [[ -z "$grant_id" ]]; then
    local payload
    payload=$(jq -n --arg d "$deck_id" '{document_id: $d, subject_type: "group",
      subject_id: "leadership", effect: "allow", scope: "read", reason: "smoke.sh restore"}')
    call POST /api/access/grants root.admin -H 'Content-Type: application/json' -d "$payload"
    expect 201
    grant_id=$(jq -r '.id' "$TMP/body")
    ok "restored leadership grant=$grant_id"
  else
    ok "active leadership grant=$grant_id"
  fi

  step "ask: Q3 board deck, before revoke (john)"
  ask john.tan "What were the Q3 board deck revenue figures?"
  expect 200
  local before_allowed before_cited
  before_allowed=$(jq -r '.access_summary.allowed_count' "$TMP/body")
  before_cited=$(jq -r --arg d "$deck_id" '[.citations[] | select(.document_id == $d)] | length' "$TMP/body")
  [[ "$before_cited" -gt 0 ]] || fail "board deck not cited before revocation (scenario 4 setup)"
  ok "deck_citations=$before_cited allowed_count=$before_allowed"

  step "revoke leadership grant (root.admin)"
  call DELETE "/api/access/grants/$grant_id" root.admin
  expect 200
  jq -e '.revoked_at != null' "$TMP/body" >/dev/null 2>&1 || fail "grant not revoked"
  ok "revoked_at=$(jq -r '.revoked_at' "$TMP/body")"

  step "ask: Q3 board deck, after revoke (john)"
  ask john.tan "What were the Q3 board deck revenue figures?"
  expect 200
  local after_allowed after_cited audit_id
  after_allowed=$(jq -r '.access_summary.allowed_count' "$TMP/body")
  after_cited=$(jq -r --arg d "$deck_id" '[.citations[] | select(.document_id == $d)] | length' "$TMP/body")
  audit_id=$(jq -r '.audit_id' "$TMP/body")
  [[ "$after_cited" -eq 0 ]] || fail "board deck still cited after revocation (scenario 4)"
  [[ "$after_allowed" -lt "$before_allowed" ]] || fail "allowed_count did not drop ($before_allowed -> $after_allowed)"
  ok "deck_citations=0 allowed_count=$before_allowed->$after_allowed abstained=$(jq -r '.answer.abstained' "$TMP/body")"

  step "existence probe: deck vs missing (mei.chen)"
  call GET "/api/documents/$deck_id" mei.chen -H 'X-Request-Id: smoke-existence-probe'
  expect 404
  cp "$TMP/body" "$TMP/denied.json"
  call GET "/api/documents/$NONEXISTENT_ID" mei.chen -H 'X-Request-Id: smoke-existence-probe'
  expect 404
  if cmp -s "$TMP/denied.json" "$TMP/body"; then
    ok "byte-identical 404 ($(wc -c <"$TMP/body" | tr -d ' ') bytes)"
  elif [[ "$(jq -cS 'del(.error.request_id)' "$TMP/denied.json")" == \
    "$(jq -cS 'del(.error.request_id)' "$TMP/body")" ]]; then
    # The server generated its own request ids instead of honouring X-Request-Id.
    ok "identical 404 apart from request_id (X-Request-Id not honoured)"
  else
    fail "denied 404 differs from nonexistent 404 (scenario 3)"
  fi

  step "audit lookup of last ask (sam.lee)"
  call GET "/api/audit/events/$audit_id" sam.lee
  expect 200
  ok "$(jq -r '"action=\(.action) actor=\(.actor_id) seq=\(.seq) decisions=\(.payload.access_decisions | length)"' "$TMP/body")"

  step "audit chain verify (sam.lee)"
  call GET /api/audit/verify sam.lee
  expect 200
  jq -e '.ok == true' "$TMP/body" >/dev/null 2>&1 || fail "audit chain broken"
  ok "$(jq -r '"ok=\(.ok) length=\(.length) head=\(.head_hash[0:12])"' "$TMP/body")"

  echo "REST smoke passed."
}

case "${1:-rest}" in
  mcp) run_mcp ;;
  rest | "") run_rest ;;
  *)
    echo "usage: $0 [mcp]" >&2
    exit 2
    ;;
esac
