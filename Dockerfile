FROM python:3.9-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:99 \
    TZ=Asia/Shanghai

# 1. Install system dependencies (Chrome, Xvfb, fonts)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    xvfb \
    fonts-liberation \
    fonts-noto-cjk \
    libgconf-2-4 \
    libnss3 \
    libxss1 \
    libasound2 \
    libappindicator3-1 \
    xdg-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 2. Set working directory
WORKDIR /app

# 3. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy application code
COPY . .

# 5. Create data directory for persistence
RUN mkdir -p /app/data/users && chmod -R 777 /app/data

# 6. Start service
# Use shell form to run Xvfb and Uvicorn simultaneously
CMD ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24 > /dev/null 2>&1 & uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1"]
