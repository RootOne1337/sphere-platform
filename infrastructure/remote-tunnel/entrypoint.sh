#!/bin/sh
set -eu
umask 077
: "${REMOTE_SUBDOMAIN:?A dedicated subdomain is required}"
: "${REMOTE_SSH_HOST:?An SSH tunnel provider is required}"
mkdir -p /state
# The registered account key is mounted read-only, never baked into an image.
# Copy into this container's writable state for POSIX permissions on Windows.
: "${REMOTE_IDENTITY_FILE:=/run/secrets/serveo_identity}"
test -s "$REMOTE_IDENTITY_FILE"
cp "$REMOTE_IDENTITY_FILE" /state/identity
chmod 600 /state/identity
# Only this installation's dedicated volume holds its identity and known hosts.
# autossh owns failed-session retry; a nonzero SSH exit must not skip reconnect.
export AUTOSSH_GATETIME=0 AUTOSSH_POLL=30 AUTOSSH_FIRST_POLL=30
exec autossh -M 0 -N -T \
    -i /state/identity \
    -p "${REMOTE_SSH_PORT:-443}" \
    -o BatchMode=yes -o IdentitiesOnly=yes -o PasswordAuthentication=no \
    -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/state/known_hosts \
    -o ServerAliveInterval=20 -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes -o ConnectTimeout=15 \
    -R "${REMOTE_SUBDOMAIN}:80:public-gateway:8080" "$REMOTE_SSH_HOST"
