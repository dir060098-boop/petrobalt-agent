# Build context = frontend/ (Railway Root Directory set to frontend/)
FROM node:20-slim AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --silent

COPY . ./
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template

ENV PORT=80
ENV BACKEND_URL=http://localhost:8000

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
