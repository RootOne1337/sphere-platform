# Package the exact standalone output already tested by CI; no second npm build.
# The Ubuntu-built native dependencies require glibc, so this image uses Debian.
FROM node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20
WORKDIR /app
ARG BUILD_SHA
LABEL org.opencontainers.image.revision=$BUILD_SHA
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --chown=1001:1001 . /app/
USER 1001:1001
EXPOSE 3000
CMD ["node", "server.js"]
