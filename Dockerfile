FROM python:3.12-slim

WORKDIR /app

# System dependencies required by WeasyPrint
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# /data is the volume mount point for the SQLite DB and key material
VOLUME ["/data"]

EXPOSE 8080

# PORT env var can override the default port (must match docker-compose mapping)
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
