# Railway строит из корня репозитория — пути указываем от корня (backend/...)
FROM python:3.11-slim

WORKDIR /app

# Зависимости (все пакеты имеют pre-built wheels, компилятор не нужен)
COPY backend/pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Код приложения и Alembic
COPY backend/app     ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini .

# Непривилегированный пользователь
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head 2>&1 || echo 'Alembic: пропущено (нет DB)' ; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
