FROM python:3.12-slim

WORKDIR /app

# System dependencies required by WeasyPrint
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for running the application
RUN useradd -m -u 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# /data is the volume mount point for the SQLite DB and key material
VOLUME ["/data"]

# Ensure appuser owns the app directory and can write to /data
RUN chown -R appuser:appuser /app && mkdir -p /data && chown appuser:appuser /data

USER appuser

EXPOSE 8080

# PORT env var can override the default port (must match docker-compose mapping)
CMD uvicorn app.main:app --host 0.0.0.0 --port 8080
