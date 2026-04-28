# ── Build stage: Vite ────────────────────────────────────────────────────────
FROM node:20-slim AS builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --silent

COPY frontend/ ./
RUN npm run build
# Артефакт: /app/dist

# ── Runtime stage: nginx ──────────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Копируем собранную статику
COPY --from=builder /app/dist /usr/share/nginx/html

# Копируем конфиг nginx (с переменными — подставляются через envsubst)
COPY frontend/nginx.conf /etc/nginx/templates/default.conf.template

# nginx:alpine использует /etc/nginx/templates/*.template → envsubst при старте
# Переменные: PORT (Railway), BACKEND_URL (URL FastAPI-сервиса)
ENV PORT=80
ENV BACKEND_URL=http://localhost:8000

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
