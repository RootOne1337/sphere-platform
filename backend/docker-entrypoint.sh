#!/bin/sh
set -eu

# Bootstrap/migration commands must not allocate a metrics registry.
# Set the variable before Gunicorn/Python imports prometheus_client.
if [ "${1:-}" = "gunicorn" ]; then
    # A new private Linux directory per master avoids stale counters and never
    # deletes an operator-provided directory. Reuse is intentionally forbidden.
    umask 077
    PROMETHEUS_MULTIPROC_DIR=$(mktemp -d /tmp/sphere-prometheus.XXXXXXXX)
    export PROMETHEUS_MULTIPROC_DIR
    unset prometheus_multiproc_dir
fi

exec "$@"
