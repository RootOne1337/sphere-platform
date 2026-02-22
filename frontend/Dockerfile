# frontend/Dockerfile
# TZ-10 Web Frontend (Next.js 15)
# Детальная реализация: TZ-10 SPLIT-1 (Setup + Auth)

FROM node:20-alpine AS base

WORKDIR /app

# Зависимости
FROM base AS deps
COPY package.json package-lock.json* ./
RUN npm ci --only=production

# Builder
FROM base AS builder
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

# Runner (минимальный образ)
FROM base AS runner
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
