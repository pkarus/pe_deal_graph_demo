#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$APP_DIR/.." && pwd)"
cd "$REPO_DIR"
if ! command -v node >/dev/null 2>&1; then
  NODE_RUNTIME="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"
  export PATH="$NODE_RUNTIME:$PATH"
fi
command -v node >/dev/null || { echo 'Node.js is required; see README.md.'; exit 1; }
[[ -x .venv/bin/python ]] || { echo 'Create the repository Python environment first.'; exit 1; }
[[ -f "$APP_DIR/ui-next/node_modules/next/dist/bin/next" ]] || { echo 'Run npm ci in ui-next first.'; exit 1; }
# DEBUG is commonly a logger string; PyRel interprets it as structured config.
unset DEBUG
export RAI_CONFIG_FILE_PATH="$REPO_DIR/raiconfig.yaml"
export NEXT_TELEMETRY_DISABLED=1
mkdir -p "$APP_DIR/.runtime"
API_PID=''
UI_PID=''
cleanup() {
  [[ -z "$API_PID" ]] || kill "$API_PID" 2>/dev/null || true
  [[ -z "$UI_PID" ]] || kill "$UI_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
.venv/bin/python -m uvicorn corporate_main:app --app-dir "$APP_DIR/service" --host 127.0.0.1 --port 8000 > "$APP_DIR/.runtime/service.log" 2>&1 &
API_PID=$!
node "$APP_DIR/ui-next/node_modules/next/dist/bin/next" dev "$APP_DIR/ui-next" --hostname 127.0.0.1 --port 3000 > "$APP_DIR/.runtime/ui.log" 2>&1 &
UI_PID=$!
echo 'Corporate graph explorer: http://127.0.0.1:3000'
echo "Logs: $APP_DIR/.runtime/"
echo 'Ctrl-C stops both local services. New calculations require a READY RAI reasoner.'
wait "$API_PID" "$UI_PID"
