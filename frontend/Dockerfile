# ---------- Frontend build stage ----------
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Backend URL baked into the bundle at build time. In docker-compose the
# nginx /debate proxy handles routing, so VITE_API_URL can stay empty.
ARG VITE_API_URL
RUN npm run build

# ---------- Static serve stage ----------
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80