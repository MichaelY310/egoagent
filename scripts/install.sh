#!/usr/bin/env sh
set -eu
REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VENV="$REPO/.runtime/venv"
OFFLINE="${1:-}"
test -d "$VENV" || python3 -m venv "$VENV"
PYTHON="$VENV/bin/python"
if test "$OFFLINE" = "--offline"; then
  "$PYTHON" -m pip install --no-index --requirement "$REPO/requirements.txt"
  (cd "$REPO/harness_editor" && npm ci --offline && npm run build)
else
  "$PYTHON" -m pip install --requirement "$REPO/requirements.txt"
  (cd "$REPO/harness_editor" && npm ci && npm run build)
fi
"$PYTHON" "$REPO/scripts/egoagent.py" doctor
printf '%s\n' "Installed. Start with: $PYTHON $REPO/scripts/egoagent.py start"
