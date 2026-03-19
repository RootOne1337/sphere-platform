FROM alpine:3.19

# Serveo SSH-туннель — стабильный HTTPS с фиксированным поддоменом
# В отличие от Cloudflare Quick Tunnel, Serveo НЕ дропает idle WebSocket
# Документация: https://serveo.net

RUN apk add --no-cache openssh-client bash && \
    mkdir -p /root/.ssh && chmod 700 /root/.ssh

# Копируем SSH ключи и entrypoint
COPY keys/id_ed25519 /root/.ssh/id_ed25519
COPY entrypoint.sh /entrypoint.sh
RUN chmod 600 /root/.ssh/id_ed25519 && \
    sed -i 's/\r$//' /entrypoint.sh && \
    chmod +x /entrypoint.sh

# Healthcheck: проверяем что autossh жив
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD pgrep ssh > /dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
