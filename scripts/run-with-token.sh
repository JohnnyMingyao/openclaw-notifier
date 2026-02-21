#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WATCHER="$ROOT_DIR/scripts/watcher.py"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
LOG_DIR="$ROOT_DIR/logs"

mkdir -p "$LOG_DIR"

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

is_placeholder() {
  local v="${1:-}"
  [[ -z "$v" ]] && return 0
  [[ "$v" == __*__ ]] && return 0
  [[ "$v" == *PASTE* ]] && return 0
  return 1
}

load_token() {
  local token=""

  if [[ -n "${OPENCLAW_GATEWAY_TOKEN:-}" ]] && ! is_placeholder "${OPENCLAW_GATEWAY_TOKEN}"; then
    token="${OPENCLAW_GATEWAY_TOKEN}"
  fi

  if [[ -z "$token" ]]; then
    token="$(openclaw config get gateway.remote.token 2>/dev/null | tr -d '\r' | tail -n 1 | sed -E 's/^"|"$//g')"
  fi

  if [[ -z "$token" ]]; then
    token="$(openclaw config get gateway.auth.token 2>/dev/null | tr -d '\r' | tail -n 1 | sed -E 's/^"|"$//g')"
  fi

  # Fallback: parse ~/.openclaw/openclaw.json directly
  if [[ -z "$token" && -f "$HOME/.openclaw/openclaw.json" ]]; then
    token="$(python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / '.openclaw' / 'openclaw.json'
try:
    cfg = json.loads(p.read_text())
    g = cfg.get('gateway', {})
    t = (g.get('remote', {}) or {}).get('token') or (g.get('auth', {}) or {}).get('token') or ''
    print(t)
except Exception:
    print('')
PY
)"
  fi

  if is_placeholder "$token"; then
    token=""
  fi

  if [[ -n "$token" ]]; then
    export OPENCLAW_GATEWAY_TOKEN="$token"
    log "Gateway token refreshed"
    return 0
  fi

  log "Gateway token not found; watcher may fail auth"
  return 1
}

if [[ ! -x "$PYTHON_BIN" ]]; then
  log "Missing venv python at: $PYTHON_BIN"
  log "Run: cd '$ROOT_DIR' && python3 -m venv .venv && source .venv/bin/activate && pip install websocket-client"
  exit 1
fi

log "Reply notifier supervisor started"

while true; do
  load_token || true

  log "Starting watcher.py"
  "$PYTHON_BIN" "$WATCHER" >> "$LOG_DIR/output.log" 2>> "$LOG_DIR/error.log"
  exit_code=$?

  log "watcher.py exited with code $exit_code; retry in 2s"
  sleep 2
done
