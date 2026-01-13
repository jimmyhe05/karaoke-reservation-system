# Minimal production-like image for the Karaoke Reservation System
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Default configuration (override via envs)
ENV FLASK_APP=app.py \
    FLASK_RUN_HOST=0.0.0.0 \
    FLASK_RUN_PORT=5000 \
    DATABASE=/data/karaoke.db \
    LOG_FORMAT=json

EXPOSE 5000
VOLUME ["/data"]

CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
