# OTA release catalog concurrency and atomicity

**AUD-143 · Finding:** P1 / High operational · **scope:** backend OTA publication and removal ·
**status:** source fix on PR #19; live deployment and multi-host acceptance remain open.

## Impact

The release catalog is a JSON file shared by four Gunicorn worker processes. Before
the fix, `POST /api/v1/updates/` and `DELETE /api/v1/updates/{id}` performed a
read-modify-write without a process-shared lock. Two administrator requests could
both read the same catalog, each return success, and the later write could erase the
other operation. A process interruption during `write_text()` could also leave a
truncated file. Readers treated invalid JSON as an empty catalog, so a later write
could silently replace the damaged catalog and devices could incorrectly see no
update.

The practical effect is a missing or ambiguous OTA release after an apparently
successful publication, or a catalog that temporarily appears empty during a write.
This finding affects release management; it does not establish a failure in APK
download, installation, or device reconnect.

## Reproduction and evidence

The regression starts two independent Windows processes and calls the production
`create_release` handler from both. Each process pauses after reading the same
isolated temporary catalog, then publishes a distinct version. This reproduces the
Gunicorn process boundary without connecting to a database, live server, emulator,
or external service.

Before the fix, both handlers returned **201**, but the final catalog contained
version **501** only; expected versions were **501 and 502**. The assertion failed
on the original implementation. After the fix, the same test retains both entries.
The test uses only synthetic release metadata and a temporary directory.
[Structured before/after evidence](evidence/ota-catalog-concurrency.json).

## Root cause and fix

The mutation boundary previously covered neither the full read/append/write sequence
nor readers during the actual file rewrite. The source fix adds a sidecar `filelock`
lock around both release creation and deletion, with a five-second bound. If the
catalog remains busy, the API returns HTTP 503 with `Retry-After: 1`; request
handling does not wait indefinitely.

Writes now go to a temporary file in the catalog directory, flush and sync its
contents, then replace the catalog atomically. On POSIX, the containing directory is
also synced after replacement. Lock-free readers therefore observe a complete old
or new JSON file. Missing catalog still means a new, empty installation; unreadable,
invalid-UTF-8, malformed, or structurally invalid catalogs return HTTP 503 instead
of being treated as empty.

## Regression coverage

- The two-process publication test fails before the fix and passes after it, retaining
  both versions while both API calls return 201.
- A separate process-level create-versus-delete test confirms both distinct changes
  survive together.
- An injected replacement failure leaves the previous catalog intact and cleans the
  temporary file.
- A structurally invalid catalog fails closed with HTTP 503.
- The OTA HTTP suite passes alongside these regressions: **32 passed**.
- Ruff passes for the modified router and tests; mypy with `--follow-imports=skip`
  passes for the router. Full local mypy could not inspect the installed Python 3.13
  SQLAlchemy source because that environment file is not valid UTF-8.

## Affected files

- `backend/api/v1/updates/router.py`
- `backend/requirements.txt`
- `tests/test_updates/test_release_catalog_concurrency.py`
- `docs/audits/2026-09-24/OTA-CATALOG-CONCURRENCY.md`
- `docs/audits/2026-09-24/evidence/ota-catalog-concurrency.json`
- `docs/audits/2026-09-05/AUDIT-REPORT.md`
- `docs/audits/2026-09-05/ANDROID-OTA-DELIVERY.md`

## Residual risk and rollout boundary

The file lock coordinates processes that share this catalog path on a filesystem
with compatible local lock and atomic-replace semantics. It does **not** coordinate
separate Docker hosts with separate named volumes, and it is not a distributed lock.
Before adding backend replicas or moving the catalog to an unsupported network
filesystem, move release metadata to a transactional database and APK bytes to
durable object storage.

An operator retry after losing the HTTP response can still create a duplicate
version entry; a publication idempotency key or unique `(platform, flavor,
version_code)` policy is a separate follow-up.

This source change has not been installed in the live pilot. No backend container,
APK, release catalog, or artifact was changed by this audit step. Runtime persistence,
backup/restore, and deployment rollback remain separate acceptance gates.
