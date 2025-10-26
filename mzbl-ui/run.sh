#!/bin/bash

# MZBL Management UI - Startup Script
# This script sets up a virtual environment and runs the Flask application

set -e

echo "🚀 Starting MZBL Management UI..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install/upgrade dependencies
echo "📥 Installing dependencies..."
pip install -r requirements.txt

# Start the Flask application
echo "🌐 Starting web server..."
echo "📍 Open your browser to: http://127.0.0.1:5000"
echo "⏹️  Press Ctrl+C to stop the server"
echo ""

python app.py
