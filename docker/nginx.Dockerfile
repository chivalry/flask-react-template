# The bundle is static files, so the Node stage runs on the build machine's platform and
# only the nginx stage targets the image's platform.
FROM --platform=$BUILDPLATFORM node:22-slim AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL
ARG NODE_BUILD_HEAP_MB=1024
# CI's build job type-checks the app and its tests, so the image only bundles. The heap
# limit guards small servers, where scripts/deploy.sh builds this image.
RUN NODE_OPTIONS="--max-old-space-size=${NODE_BUILD_HEAP_MB}" npx vite build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
