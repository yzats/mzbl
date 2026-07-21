#!/bin/bash

# MZBL Management UI - Startup Script
# This script uses the root uv environment and runs the Flask application

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🚀 Starting MZBL Management UI..."

if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  echo "🔧 Creating uv environment..."
  "$ROOT_DIR/install-prereqs.sh"
fi

cd "$SCRIPT_DIR"

# Start the Flask application
echo "🌐 Starting web server..."
echo "📍 Open your browser to: http://127.0.0.1:5000"
echo "⏹️  Press Ctrl+C to stop the server"
echo ""

"$ROOT_DIR/.venv/bin/python" app.py
