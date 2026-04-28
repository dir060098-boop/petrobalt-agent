# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Системные зависимости для компиляции asyncpg / pdfplumber
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .

# PyMuPDF публикует pre-built wheels на PyPI — устанавливается без компиляции.
# Ставим все зависимости из pyproject.toml.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Только runtime-зависимости ОС (libpq для asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Копируем установленные пакеты из builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копируем код приложения и Alembic
COPY app     ./app
COPY alembic ./alembic
COPY alembic.ini .

# Непривилегированный пользователь
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Применяем миграции (best-effort) и стартуем uvicorn
CMD ["sh", "-c", "alembic upgrade head 2>&1 || echo 'Alembic: миграции пропущены (нет DB)' && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
