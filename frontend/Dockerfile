# frontend/Dockerfile
# TZ-10 Web Frontend (Next.js 15)
# Детальная реализация: TZ-10 SPLIT-1 (Setup + Auth)

FROM node:24-alpine AS base

WORKDIR /app

# Зависимости
FROM base AS deps
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev --no-audit --no-fund

# Reuse dependency layers across source revisions. The revision must not enter
# npm ci's cache key; otherwise each reviewed commit installs another full copy.
FROM base AS build-deps
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund && npm cache clean --force

# Builder
FROM build-deps AS builder
COPY . .
ARG BUILD_SHA=unknown
ENV NEXT_PUBLIC_BUILD_SHA=${BUILD_SHA}
# Keep generated types/standalone output, but do not retain incremental build
# caches in every exported verification image.
RUN npm run build && rm -rf /app/.next/cache

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
