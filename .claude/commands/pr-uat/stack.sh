#!/bin/bash
# Start, stop or show the /pr-uat stack for a checkout: the web server (background tasks run inside it, there is no
# worker) and a fake Pipedrive, TC2 and Google Calendar, all on that checkout's code, with test-only keys.
#
# Usage:
#   stack.sh start <checkout> [--fresh]    (re)start; --fresh rebuilds the stack's own database and Redis db
#   stack.sh stop <checkout>
#   stack.sh status <checkout>
#
# The stack never reaches anything real, whatever .env holds:
#   - Every key is a test value and telemetry is off, so no real secret can appear in a screenshot.
#   - The Pipedrive and TC2 URLs always point at fake_services.py, and uat_app.py does the same for Google Calendar,
#     so no record, invite or email can leave the machine.
#   - A database or Redis on a remote host is refused before any DDL runs.
#
# Database and Redis: the stack always gets its own database (hermes_uat_<n>) and Redis db number, on the local
# servers .env points at, so it never shares rows with the checkout's dev database or with another checkout.
#
# Any other setting a case needs goes on the environment of `start`, e.g.
#   SYNC_CREATE_DEALS=false stack.sh start <checkout>
# Journeys `source "$STACK_DIR/env.sh"` (path printed by start and status) for the URL, keys and helpers.
set -euo pipefail

ACTION=${1:?usage: stack.sh start|stop|status <checkout> [--fresh]}
CHECKOUT="$(cd "${2:?usage: stack.sh start|stop|status <checkout> [--fresh]}" && pwd)"
FRESH=${3:-}
HERE="$(cd "$(dirname "$0")" && pwd)"
n=$(printf '%s' "$CHECKOUT" | cksum | awk '{print $1 % 100000}')
STACK_DIR="/tmp/uat-stack-$(basename "$CHECKOUT")-$n"
mkdir -p "$STACK_DIR/tc2-clients"
cd "$CHECKOUT"

stop() {
  for name in web services; do
    if [ -f "$STACK_DIR/$name.pid" ]; then
      kill "$(cat "$STACK_DIR/$name.pid")" 2>/dev/null || true
      rm -f "$STACK_DIR/$name.pid"
    fi
  done
  # `uv run` starts a child: the parent pid alone can leave it on the port.
  pkill -f "uvicorn uat_app:app --port $(cat "$STACK_DIR/port" 2>/dev/null || echo none)" 2>/dev/null || true
  pkill -f "fake_services.py --dir $STACK_DIR" 2>/dev/null || true
}

status() {
  for name in web services; do
    if [ -f "$STACK_DIR/$name.pid" ] && kill -0 "$(cat "$STACK_DIR/$name.pid")" 2>/dev/null; then
      echo "$name: running (pid $(cat "$STACK_DIR/$name.pid"), log $STACK_DIR/$name.log)"
    else
      echo "$name: stopped"
    fi
  done
  [ -f "$STACK_DIR/summary" ] && cat "$STACK_DIR/summary"
  return 0
}

free_port() {
  for candidate in $(seq "$1" "$2"); do
    if ! lsof -nP -iTCP:"$candidate" -sTCP:LISTEN -t >/dev/null 2>&1; then echo "$candidate"; return 0; fi
  done
  echo "no free port in $1-$2" >&2
  return 1
}

case "$ACTION" in
  stop) stop; echo "stopped"; exit 0 ;;
  status) status; exit 0 ;;
  start) ;;
  *) echo "unknown action: $ACTION" >&2; exit 2 ;;
esac
if [ -n "$FRESH" ] && [ "$FRESH" != "--fresh" ]; then echo "unknown option: $FRESH" >&2; exit 2; fi

stop

# Hermes has no default for this, and the app does not start without it.
if [ -z "${REDISCLOUD_URL:-}" ] && ! grep -qE '^REDISCLOUD_URL=' .env 2>/dev/null; then
  export REDISCLOUD_URL='redis://localhost:6379'
fi

# Before anything writes. Prints the stack's own URLs, built from the local servers the checkout points at.
URLS=$(UAT_N="$n" uv run python -c "
import os, sys
from urllib.parse import urlsplit
from app.core.config import settings
n = int(os.environ['UAT_N'])
database, redis = urlsplit(str(settings.database_url)), urlsplit(settings.redis_url)
for name, url in (('database', database), ('redis', redis)):
    if url.hostname not in {'localhost', '127.0.0.1', '::1'}:
        sys.exit(f'refusing to start: the {name} is not on this machine; set a local URL for /pr-uat')
print(database._replace(path='/postgres').geturl())
print(database._replace(path=f'/hermes_uat_{n}').geturl())
print(redis._replace(path=f'/{n % 15 + 1}').geturl())
")
PG_ADMIN=$(echo "$URLS" | sed -n 1p)
OWN_DB="hermes_uat_$n"
export DATABASE_URL=$(echo "$URLS" | sed -n 2p)
export REDISCLOUD_URL=$(echo "$URLS" | sed -n 3p)

SERVICES_PORT=$(free_port 8350 8399)
# Not overridable: these are what guarantee nothing real is called or reported to.
export TC2_API_KEY=uat-tc2-key
export PD_API_KEY=uat-pd-key
export SIGNING_KEY=uat-signing-key
export PD_WEBHOOK_USERNAME=hermes
export PD_WEBHOOK_PASSWORD=uat-pd-webhook-password
export PD_BASE_URL="http://127.0.0.1:$SERVICES_PORT/pipedrive"
export TC2_BASE_URL="http://127.0.0.1:$SERVICES_PORT/tc2"
export UAT_GOOGLE_URL="http://127.0.0.1:$SERVICES_PORT/google/calendar/v3/"
export G_PRIVATE_KEY=''
export G_PRIVATE_KEY_ID=''
export SENTRY_DSN=''
export LOGFIRE_TOKEN=''
export DEV_MODE=false

if [ -n "$FRESH" ]; then
  psql "$PG_ADMIN" -qc "DROP DATABASE IF EXISTS $OWN_DB WITH (FORCE)"
  redis-cli -u "$REDISCLOUD_URL" FLUSHDB >/dev/null
  rm -f "$STACK_DIR/service-requests.jsonl" "$STACK_DIR/google-busy.json" "$STACK_DIR"/tc2-clients/*.json
fi
psql "$PG_ADMIN" -tAc "SELECT 1 FROM pg_database WHERE datname = '$OWN_DB'" | grep -q 1 \
  || psql "$PG_ADMIN" -qc "CREATE DATABASE $OWN_DB"
uv run alembic upgrade head
PYTHONPATH="$CHECKOUT" uv run python "$HERE/seed.py"

PORT=$(free_port 8300 8349)
echo "$PORT" > "$STACK_DIR/port"

# Output goes to a file: a backgrounded process whose stdout pipe closes dies on its next write.
nohup uv run python "$HERE/fake_services.py" --dir "$STACK_DIR" --port "$SERVICES_PORT" \
  >"$STACK_DIR/services.log" 2>&1 &
echo $! > "$STACK_DIR/services.pid"
PYTHONPATH="$CHECKOUT" nohup uv run uvicorn uat_app:app --port "$PORT" --app-dir "$HERE" >"$STACK_DIR/web.log" 2>&1 &
echo $! > "$STACK_DIR/web.pid"
disown -a

{
  printf 'export UAT_URL=%q\n' "http://127.0.0.1:$PORT"
  printf 'export SERVICES_URL=%q\n' "http://127.0.0.1:$SERVICES_PORT"
  printf 'export STACK_DIR=%q\n' "$STACK_DIR"
  printf 'export DATABASE_URL=%q\n' "$DATABASE_URL"
  printf 'export REDISCLOUD_URL=%q\n' "$REDISCLOUD_URL"
  printf 'export TC2_API_KEY=%q\n' "$TC2_API_KEY"
  printf 'export PD_WEBHOOK_USERNAME=%q\n' "$PD_WEBHOOK_USERNAME"
  printf 'export PD_WEBHOOK_PASSWORD=%q\n' "$PD_WEBHOOK_PASSWORD"
  printf 'export SIGNING_KEY=%q\n' "$SIGNING_KEY"
  printf 'export PAGER=cat\n'
  printf 'run() { printf %q "$*"; eval "$*"; }\n' '$ %s\n'
  cat <<'HELPER'
# api <METHOD> <path> [curl args]: a request as TC2 makes it, with the status line after the body.
api() { local m=$1 p=$2; shift 2; curl -sS -w '\nHTTP %{http_code}\n' -X "$m" -H "Authorization: Bearer $TC2_API_KEY" -H 'Content-Type: application/json' "$UAT_URL$p" "$@"; }
# public <METHOD> <path> [curl args]: a request as the website makes it, with no credentials.
public() { local m=$1 p=$2; shift 2; curl -sS -w '\nHTTP %{http_code}\n' -X "$m" -H 'Content-Type: application/json' "$UAT_URL$p" "$@"; }
# tc2_hook '<json>': the body signed the way Chronos signs it.
tc2_hook() { local sig; sig=$(printf '%s' "$1" | openssl dgst -sha256 -hmac "$TC2_API_KEY" -r | cut -d' ' -f1); curl -sS -w '\nHTTP %{http_code}\n' -H 'Content-Type: application/json' -H "webhook-signature: $sig" --data-binary "$1" "$UAT_URL/tc2/callback/"; }
# pd_hook '<json>': the body with the Basic auth set on the Pipedrive webhook.
pd_hook() { curl -sS -w '\nHTTP %{http_code}\n' -u "$PD_WEBHOOK_USERNAME:$PD_WEBHOOK_PASSWORD" -H 'Content-Type: application/json' -d "$1" "$UAT_URL/pipedrive/callback/"; }
# calls [path fragment]: what the fake services received, oldest first, one request a line.
calls() { grep -F "${1:-}" "$STACK_DIR/service-requests.jsonl" 2>/dev/null || true; }
# fail_next <status> <path fragment> [count]: the next requests with that fragment fail with that status.
fail_next() { curl -sS -d "{\"path\": \"$2\", \"status\": $1, \"count\": ${3:-1}}" "$SERVICES_URL/_uat/fail"; echo; }
HELPER
} > "$STACK_DIR/env.sh"
{
  echo "server: http://127.0.0.1:$PORT/"
  echo "env: source $STACK_DIR/env.sh"
  echo "database: $OWN_DB"
  echo "service requests: $STACK_DIR/service-requests.jsonl"
} > "$STACK_DIR/summary"

for _ in $(seq 40); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    cat "$STACK_DIR/summary"
    exit 0
  fi
  sleep 0.5
done
echo "server FAILED to start: $STACK_DIR/web.log" >&2
tail -20 "$STACK_DIR/web.log" >&2
exit 1
