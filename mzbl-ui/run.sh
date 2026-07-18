#!/bin/bash

# MZBL Management UI - Startup Script
# This script sets up a virtual environment and runs the Flask application

set -e

echo "🚀 Starting MZBL Management UI..."


# Activate virtual environment
echo "🔧 Activating virtual environment..."
source ~/devl/mzbl/myenv/bin/activate


# Start the Flask application
echo "🌐 Starting web server..."
echo "📍 Open your browser to: http://127.0.0.1:5000"
echo "⏹️  Press Ctrl+C to stop the server"
echo ""

python app.py
