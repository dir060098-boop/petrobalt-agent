FROM python:3.11-slim

WORKDIR /app

# Все зависимости (asyncpg, PyMuPDF, pdfplumber) имеют pre-built wheels —
# компилятор и системные dev-пакеты не нужны.
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Копируем код приложения и Alembic
COPY app     ./app
COPY alembic ./alembic
COPY alembic.ini .

# Непривилегированный пользователь
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Применяем миграции (best-effort) и запускаем uvicorn
CMD ["sh", "-c", "alembic upgrade head 2>&1 || echo 'Alembic: пропущено (нет DB)' ; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
