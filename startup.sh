#!/bin/bash

echo "🧹 Cleaning all Chromium data..."

# Clean Chromium global config (running as root in Docker)
rm -rf /root/.config/chromium 2>/dev/null
rm -rf /root/.cache/chromium 2>/dev/null
rm -rf /root/.local/share/chromium 2>/dev/null

# Clean DrissionPage cache
rm -rf /root/.DrissionPage 2>/dev/null

# Clean temp files
rm -rf /tmp/.org.chromium.* 2>/dev/null
rm -rf /tmp/chromium* 2>/dev/null

# Clean user data
rm -rf /app/data/users/* 2>/dev/null
rm -rf /src/data/users/* 2>/dev/null
rm -rf data/users/* 2>/dev/null

echo "✅ Chromium data cleaned"

# Start Xvfb
Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &

# Start the application
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
