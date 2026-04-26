FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY src_front/ ./src_front/
COPY vite.config.ts tsconfig*.json ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host"]
