# ── Stage 1: build the React/Vite SPA ────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Install deps first (cached unless package*.json changes)
COPY package*.json ./
RUN npm ci

# Vite inlines VITE_* env vars at build time — pass them as build args.
# VITE_API_BASE_URL defaults to "" (relative) which works behind nginx proxy.
ARG VITE_API_BASE_URL=""
ARG VITE_API_SECRET_KEY
ARG VITE_POSTHOG_KEY=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_API_SECRET_KEY=$VITE_API_SECRET_KEY
ENV VITE_POSTHOG_KEY=$VITE_POSTHOG_KEY

# Copy source and build
COPY . .
RUN npm run build

# ── Stage 2: serve with nginx ─────────────────────────────────────────────────
FROM nginx:alpine

# Copy static build output
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx config: SPA fallback + API proxy to the backend service
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
