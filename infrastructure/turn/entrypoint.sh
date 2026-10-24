#!/bin/sh
set -eu
umask 077

# Do not place the shared key in command arguments, environment or Docker logs.
# The key files must be readable by UID 65534; host permissions remain operator-owned.
for item in turn-rest-key turn-tls-chain.pem turn-tls-key.pem; do
    test -s "/run/secrets/$item" || { echo 'Missing or unreadable TURN secret file' >&2; exit 78; }
done
host=${SPHERE_TURN_HOST:-}
test "${#host}" -le 253 && printf '%s' "$host" | LC_ALL=C grep -Eq '^[a-z0-9][a-z0-9.-]*\.[a-z][a-z0-9-]*$' || {
    echo 'Missing or invalid relay hostname' >&2; exit 78;
}
# Coturn can continue with UDP when TLS material is invalid. Reject that partial
# startup before binding any listeners. Never print OpenSSL key diagnostics.
openssl x509 -in /run/secrets/turn-tls-chain.pem -noout -checkend 0 >/dev/null 2>&1 &&
openssl x509 -in /run/secrets/turn-tls-chain.pem -noout -checkhost "$host" >/dev/null 2>&1 &&
openssl x509 -in /run/secrets/turn-tls-chain.pem -noout -pubkey -out /tmp/turn-cert-public.pem >/dev/null 2>&1 &&
openssl pkey -in /run/secrets/turn-tls-key.pem -passin pass: -pubout -out /tmp/turn-key-public.pem >/dev/null 2>&1 &&
cmp -s /tmp/turn-cert-public.pem /tmp/turn-key-public.pem || {
    echo 'Invalid, expired or mismatched relay TLS identity' >&2; exit 78;
}
rm -f /tmp/turn-cert-public.pem /tmp/turn-key-public.pem
key=$(cat /run/secrets/turn-rest-key)
test "${#key}" -eq 64 && printf '%s' "$key" | LC_ALL=C grep -Eq '^[0-9a-f]{64}$' || {
    echo 'Invalid TURN REST key format' >&2; exit 78;
}
cat /etc/sphere-turn/turnserver.conf > /tmp/sphere-turn.conf
printf '\nstatic-auth-secret=%s\n' "$key" >> /tmp/sphere-turn.conf
unset key
exec turnserver -c /tmp/sphere-turn.conf
