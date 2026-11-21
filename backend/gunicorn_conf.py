"""Retain dead-worker totals until the owning master has stopped its children."""
import logging
import os
import re
import shutil
import stat
from pathlib import Path

from prometheus_client import multiprocess

# Fixed namespace, not an insecure temporary file: the entrypoint uses mktemp
# with umask 077, and cleanup verifies private ownership before accessing it.
_REGISTRY_ROOT = Path("/tmp/sphere-metrics")  # nosec B108
_REGISTRY_NAME = re.compile(r"master\.[A-Za-z0-9]{8}\Z")
_logger = logging.getLogger(__name__)


def child_exit(server, worker):
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if directory:
        multiprocess.mark_process_dead(worker.pid, path=directory)


def on_exit(server):
    """Gunicorn calls this after stop/reap, never during worker replacement.

    Only remove the entrypoint-created directory owned by THIS master. Do not
    sweep neighbouring directories or touch a user-supplied Prometheus path.
    SIGKILL cannot run this hook; the production tmpfs is cleared on container
    stop and bounds that exceptional residual storage.
    """
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not directory:
        return
    if getattr(server, "WORKERS", None):
        _logger.warning("Metrics registry retained: workers have not exited")
        return
    try:
        path = Path(directory)
        if _REGISTRY_ROOT.is_symlink() or path.is_symlink():
            raise ValueError("Symlink registry")
        root = _REGISTRY_ROOT.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if not path.is_absolute() or resolved.parent != root or not _REGISTRY_NAME.fullmatch(path.name):
            raise ValueError("Registry is outside the owned root")
        owner = str(os.getpid())
        if os.environ.get("SPHERE_METRICS_OWNER_PID") != owner:
            raise ValueError("Not the registry owner process")
        metadata = resolved.stat()
        uid = getattr(os, "geteuid", lambda: metadata.st_uid)()
        if metadata.st_uid != uid or (os.name == "posix" and stat.S_IMODE(metadata.st_mode) != 0o700):
            raise ValueError("Not a private owned directory")
        marker = resolved / ".owner"
        marker_stat = marker.lstat()
        if not stat.S_ISREG(marker_stat.st_mode) or marker_stat.st_uid != uid:
            raise ValueError("Not an owned regular marker")
        with marker.open("rb") as source:
            if source.read(32).strip() != owner.encode():
                raise ValueError("Registry marker does not identify this master")
        # Absolute target and ownership are established; rmtree doesn't follow
        # symlinks within the directory. Active masters/adjacent files survive.
        shutil.rmtree(resolved)
    except (OSError, ValueError) as exc:
        _logger.warning("Metrics registry cleanup refused: %s", type(exc).__name__)
