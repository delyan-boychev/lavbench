# Stage 1: Build the React application
FROM node:26-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Stage 2: Serve using Nginx
FROM nginx:1.31-alpine

# Apply current Alpine security fixes before dropping privileges
RUN apk upgrade --no-cache

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom nginx configuration for routing and proxying
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Optional TLS listener (443). Activated by the entrypoint only when the
# self-signed cert (./certs/web/lavbench.crt) is mounted at /etc/nginx/ssl.
COPY ssl.conf.disabled /etc/nginx/conf.d/ssl.conf.disabled
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh \
    && mkdir -p /app/logs /var/cache/nginx /run \
    && chown -R nginx:nginx /app/logs /var/cache/nginx /run /etc/nginx/conf.d

# Run nginx master and workers as the non-root nginx user. The entrypoint's
# TLS activation writes to /etc/nginx/conf.d, which is nginx-owned above.
USER nginx

EXPOSE 80 443

CMD ["/docker-entrypoint.sh"]
