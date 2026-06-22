# ─── Builder ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Build deps for any C-extension wheels (psycopg2 etc.).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

# Install the package with all the optional framework dependencies the demo uses.
RUN pip install --no-cache-dir --prefix=/install ".[flask,redis,celery,dev]"

# ─── Runtime ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy the installed site-packages and console scripts from the builder.
COPY --from=builder /install /usr/local

# Copy the demo application.
COPY demo ./demo

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    REDIS_URL=redis://redis:6379/0 \
    DATABASE_URL=sqlite:///demo_orders.db

EXPOSE 8000

# Run the Flask demo. Start a Celery worker separately:
#   docker compose run --rm app celery -A demo.celery_app worker --loglevel=info
CMD ["python", "demo/app.py"]
