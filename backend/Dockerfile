# Build context = backend/ (Railway Root Directory set to backend/)
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

COPY app     ./app
COPY alembic ./alembic
COPY alembic.ini .

RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head 2>&1 || echo 'Alembic: пропущено (нет DB)' ; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
