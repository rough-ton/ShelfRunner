FROM python:3.12-slim

WORKDIR /app

# Install deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Download dir (can be overridden with a volume mount)
RUN mkdir -p /downloads

EXPOSE 5000

# Single worker with multiple threads: required so the in-memory _jobs dict
# is shared between request handlers and background watcher threads.
# Multi-worker (fork) mode would give each worker its own _jobs copy.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--timeout", "120", "server:app"]
