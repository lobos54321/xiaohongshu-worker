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

# Kill any existing Xvfb instances
echo "🔍 Checking for existing Xvfb instances..."
pkill -f "Xvfb :99" 2>/dev/null || true
sleep 1

# Start Xvfb with proper settings
echo "🖥️ Starting Xvfb..."
Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &
XVFB_PID=$!
sleep 2

# Check if Xvfb started successfully
if kill -0 $XVFB_PID 2>/dev/null; then
    echo "✅ Xvfb started successfully (PID: $XVFB_PID)"
else
    echo "❌ Failed to start Xvfb, retrying..."
    Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 &
    XVFB_PID=$!
    sleep 2
    if kill -0 $XVFB_PID 2>/dev/null; then
        echo "✅ Xvfb retry successful (PID: $XVFB_PID)"
    else
        echo "⚠️ Xvfb failed to start, continuing anyway..."
    fi
fi

# Export DISPLAY environment variable
export DISPLAY=:99
echo "📺 DISPLAY set to $DISPLAY"

# Start the application
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
