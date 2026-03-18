FROM python:3.11-slim

# Install system deps needed by asyncpg (libpq) and pip compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies before copying source so this layer is cached
# whenever requirements.txt is unchanged.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Run as a non-root user — principle of least privilege
RUN useradd -m -u 1000 ada && chown -R ada:ada /app
USER ada

EXPOSE 8889

# python -m uvicorn ensures the venv's uvicorn is used, not a system-level one.
# --host 0.0.0.0 required inside a container (default 127.0.0.1 is unreachable from outside).
CMD ["python", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8889"]
