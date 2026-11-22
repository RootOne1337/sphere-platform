#!/bin/sh
set -eu

# Bootstrap/migration commands must not allocate a metrics registry.
# Set the variable before Gunicorn/Python imports prometheus_client.
if [ "${1:-}" = "gunicorn" ]; then
    # A new private Linux directory per master avoids stale counters and never
    # deletes an operator-provided directory. Reuse is intentionally forbidden.
    umask 077
    mkdir -p /tmp/sphere-metrics
    PROMETHEUS_MULTIPROC_DIR=$(mktemp -d /tmp/sphere-metrics/master.XXXXXXXX)
    SPHERE_METRICS_OWNER_PID=$$
    printf '%s\n' "$SPHERE_METRICS_OWNER_PID" > "$PROMETHEUS_MULTIPROC_DIR/.owner"
    export PROMETHEUS_MULTIPROC_DIR SPHERE_METRICS_OWNER_PID
    unset prometheus_multiproc_dir
fi

exec "$@"
