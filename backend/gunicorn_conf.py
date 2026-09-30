"""Retire only dead-worker live gauges; retain counters until master restart."""
import os

from prometheus_client import multiprocess


def child_exit(server, worker):
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if directory:
        multiprocess.mark_process_dead(worker.pid, path=directory)
