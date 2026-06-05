#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  VENV_DIR="$VIRTUAL_ENV"
elif [[ -n "${VENV_DIR:-}" ]]; then
  VENV_DIR="$(cd "$VENV_DIR" && pwd)"
elif [[ -d "$ROOT_DIR/myenv" ]]; then
  VENV_DIR="$ROOT_DIR/myenv"
elif [[ -d "$ROOT_DIR/.venv" ]]; then
  VENV_DIR="$ROOT_DIR/.venv"
elif [[ -d "$ROOT_DIR/venv" ]]; then
  VENV_DIR="$ROOT_DIR/venv"
else
  VENV_DIR="$ROOT_DIR/.venv"
  "${PYTHON_BIN:-python3}" -m venv "$VENV_DIR"
fi

if [[ -x "$VENV_DIR/bin/python" ]]; then
  PYTHON="$VENV_DIR/bin/python"
elif [[ -x "$VENV_DIR/Scripts/python.exe" ]]; then
  PYTHON="$VENV_DIR/Scripts/python.exe"
else
  echo "Could not find a Python executable in venv: $VENV_DIR" >&2
  exit 1
fi

echo "Using venv: $VENV_DIR"
"$PYTHON" -m pip install --upgrade pip setuptools wheel

"$PYTHON" -m pip install --upgrade \
  -r "$ROOT_DIR/sqs_shared/requirements.txt" \
  -r "$ROOT_DIR/sqs-stock-remover/requirements.txt" \
  -r "$ROOT_DIR/sqs-image-uploader/requirements.txt" \
  pandas \
  Flask

"$PYTHON" - <<'PY'
from importlib import metadata

import flask  # noqa: F401
import pandas  # noqa: F401
import requests  # noqa: F401

print("Verified imports:")
print(f"  Flask {metadata.version('flask')}")
print(f"  pandas {metadata.version('pandas')}")
print(f"  requests {metadata.version('requests')}")
PY

echo "Python prerequisites are installed."
