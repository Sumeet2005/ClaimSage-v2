# Stage 1: Build the React application
FROM node:22-alpine AS builder

WORKDIR /app

# Copy package manifests and install locked dependencies
COPY package.json package-lock.json ./
RUN npm ci

# Copy frontend source and build production bundle
COPY . .
RUN npm run build

# Stage 2: Serve production SPA with Nginx
FROM nginx:1.27-alpine

# Remove default nginx configurations
RUN rm -rf /etc/nginx/conf.d/*

# Copy custom Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
