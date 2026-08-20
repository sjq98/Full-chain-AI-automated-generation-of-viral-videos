#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$ROOT/vendor/MediaCrawler/.venv/bin/python"
PORT="8789"
LOG_DIR="$ROOT/.logs"
LOG_FILE="$LOG_DIR/workbench.log"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This launcher is for macOS only."
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "Dependencies are not installed yet. Double-click macos-install.command first."
  read -r -p "Press Return to close this window..."
  exit 1
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  open "http://127.0.0.1:$PORT/"
  echo "The workbench is already running at http://127.0.0.1:$PORT/"
  read -r -p "Press Return to close this window..."
  exit 0
fi

mkdir -p "$LOG_DIR"
cd "$ROOT"
HOST="127.0.0.1" PORT="$PORT" "$PYTHON" "$ROOT/app.py" >"$LOG_FILE" 2>&1 &
BACKEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 40); do
  if curl --silent --fail "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then
    open "http://127.0.0.1:$PORT/"
    echo "MP4 Golden Clip Workbench is running. Keep this Terminal window open while you use it."
    echo "Log file: $LOG_FILE"
    wait "$BACKEND_PID"
    exit $?
  fi
  sleep 1
done

echo "The workbench did not start. Recent log output:"
tail -n 40 "$LOG_FILE" || true
read -r -p "Press Return to close this window..."
exit 1
