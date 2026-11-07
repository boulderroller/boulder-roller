# Stage 1: Install dependencies and build TypeScript
FROM node:20-alpine AS builder

WORKDIR /app

# Install exactly what package-lock.json pins, as CI does, so the image runs
# the versions that were tested and audited.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src/ ./src/

RUN npm run build

# Stage 2: Production image
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules

# Default IDL directory (overridden by volume mount or IDL_PATH env var)
RUN mkdir -p /app/idl

# Default env: IDL_PATH points to the volume mount location
ENV IDL_PATH=/app/idl/boulder_rollers.json

EXPOSE 3001

CMD ["node", "dist/index.js"]
