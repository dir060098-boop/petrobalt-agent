# Build context = frontend/ (Railway Root Directory set to frontend/)
FROM node:20-slim AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --silent

COPY . ./

# Vite embeds env vars at build time — Railway passes VITE_* as build args
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template

ENV PORT=80

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
