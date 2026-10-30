# Trusted local packaging from a canonical Git context; no Windows native modules.
ARG NODE_BASE_IMAGE=public.ecr.aws/docker/library/node@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20
FROM ${NODE_BASE_IMAGE} AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY . .
ARG BUILD_SHA
ENV NEXT_PUBLIC_BUILD_SHA=${BUILD_SHA}
RUN npm run build

FROM ${NODE_BASE_IMAGE}
WORKDIR /app
ARG BUILD_SHA
ARG LOCAL_RUN
ARG SOURCE_DIGEST
LABEL org.opencontainers.image.revision=$BUILD_SHA io.sphere.local.run=$LOCAL_RUN io.sphere.local.source=$SOURCE_DIGEST
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=builder --chown=1001:1001 /app/.next/standalone ./
COPY --from=builder --chown=1001:1001 /app/.next/static ./.next/static
COPY --from=builder --chown=1001:1001 /app/public ./public
USER 1001:1001
EXPOSE 3000
CMD ["node", "server.js"]
