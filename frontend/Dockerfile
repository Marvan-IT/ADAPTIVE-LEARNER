# ── Stage 1: build the React/Vite SPA ────────────────────────────────────────
# node:20-alpine keeps the builder image small; the output dist/ folder is
# copied into the much smaller nginx stage so the final image has no Node.js.
FROM node:20-alpine AS builder

WORKDIR /app

# Install deps first (cached unless package*.json changes)
COPY package*.json ./
RUN npm ci

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
