FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY src_front/ ./src_front/
COPY vite.config.ts tsconfig*.json ./

EXPOSE 5173

# --port pins the container port: FRONTEND_PORT is a host-side setting that
# docker-compose.yml maps onto 5173, so Vite must not read it in here.
CMD ["npm", "run", "dev", "--", "--host", "--port", "5173"]
