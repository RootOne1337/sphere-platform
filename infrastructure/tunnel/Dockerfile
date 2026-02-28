FROM cloudflare/cloudflared:latest

# cloudflared quick tunnel — не требует аккаунта, даёт HTTPS автоматически
# Документация: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/

# Healthcheck: проверяем что процесс живой
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD pgrep cloudflared > /dev/null || exit 1

# Точка входа переопределяется в docker run / compose
ENTRYPOINT ["cloudflared", "tunnel", "--no-autoupdate"]
