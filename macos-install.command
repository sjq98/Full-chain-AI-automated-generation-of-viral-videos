#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/vendor/MediaCrawler/.venv"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This installer is for macOS only."
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install Homebrew first, then run this file again."
  echo "See: https://brew.sh"
  exit 1
fi

echo "Installing macOS dependencies. This may take several minutes..."
brew install python@3.11 ffmpeg

PYTHON="$(brew --prefix python@3.11)/bin/python3.11"
if [[ ! -x "$PYTHON" ]]; then
  echo "Python 3.11 was not found after installation."
  exit 1
fi

"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$ROOT/requirements.txt"
"$VENV/bin/python" -m pip install -r "$ROOT/vendor/MediaCrawler/requirements.txt"
"$VENV/bin/python" -m pip install yt-dlp
"$VENV/bin/python" -m playwright install chromium

if ! open -Ra "Google Chrome"; then
  echo
  echo "Google Chrome was not found. The workbench can start, but MediaCrawler platform search requires Chrome."
fi

echo
echo "Installation complete. Double-click macos-start.command to launch the workbench."
read -r -p "Press Return to close this window..."
