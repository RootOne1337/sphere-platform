# AUD-143: Redis OOM under concurrent AOF rewrite

**23 September 2026 · F32-32 · P1 / High · isolated persistence gate passed; fleet/pilot gates remain open.**

[Fleet32](FLEET32-PREFLIGHT.md) · [Redis contract](../../operations/REDIS-MEMORY.md) ·
[Prior AUD-139 evidence](REDIS-MEMORY.md) · [CI run](https://github.com/RootOne1337/sphere-platform/actions/runs/35789088762)

## Finding

The Redis runtime probe on PR head `e635de8` ran after the backend suite had
completed with 1,996 tests, 0 failures, 0 errors and 15 skips. Its disposable,
network-isolated Redis container was capped at 1536 MiB with swap disabled. The
probe first wrote 14,000 values of 64 KiB (about 875 MiB offered) to reach the
512 MiB `maxmemory`/eviction boundary, then repeated writes while `BGREWRITEAOF`
and `BGSAVE` ran. The container exited 137 with `OOMKilled=true` during this
concurrent persistence workload. At the preceding fill checkpoint, Redis reported
about 704 MiB `used_memory` and 192 MiB in the AOF buffer. The harness removed its
own labeled container; no installed or live pilot service was involved.

The earlier AUD-139 probe passed at 1536 MiB with a different measured cgroup
peak. That historical pass does not cover this later overlap and is not evidence
that 1536 MiB is sufficient for concurrent write/AOF bursts.

## Root cause and fix

`maxmemory` caps the evictable dataset, not total cgroup usage. During persistence,
Redis also needs process/allocator memory, AOF/client buffers, copy-on-write pages
and charged filesystem cache. The previous 3× baseline left too little headroom for
the observed workload. Base and production Compose now set a 2048 MiB ceiling while
keeping the 512 MiB dataset, eviction policy and persistence settings unchanged.
The Compose regression now requires a 4× dataset-to-container ratio across its
seven runtime combinations.

The limit is a ceiling, not a reservation. A larger configured budget does not
prove that a host has enough physical memory or establish capacity for streams,
subscribers, reconnect bursts, or arbitrary client buffers.

## Verification status

- **Before fix:** isolated CI runtime probe reproduced OOM; exit 137 and
  `OOMKilled=true` were read from the exact harness-owned container state.
- **Source regression:** `tests/deployment/test_redis_memory_budget.py` renders
  the seven runtime Compose combinations and checks the 4× minimum plus the
  unchanged 512 MiB dataset and AOF/everysec/allkeys-lru settings; all 8 tests pass.
- **After fix:** PR head `bee9bc0`, CI run `35792035327` passed the 2048 MiB runtime
  probe. Both concurrent persistence operations finished with status `ok`; graceful
  restart preserved 6,531 keys and the marker; final state had `OOMKilled=false`.
  The cgroup peak was exactly **2,147,483,648 bytes**, equal to its hard limit. This
  closes the reproduced isolated OOM case but demonstrates no spare cgroup margin.
- **Repeat:** PR head `6868f92`, CI run `35795606456`, repeated the same isolated
  acceptance successfully: `passed=true`, network `none`, no published ports,
  container removed, limit/swap each 2,147,483,648 bytes, AOF/BGSAVE/restart passed,
  6,531 keys and marker survived, `OOMKilled=false`, restart count zero. This run's
  cgroup peak was **1,603,907,584 bytes** (~1.49 GiB), below the ceiling. Across the
  two post-fix runs the observed peak range is 1.49–2.00 GiB; the maximum reached the
  limit. The difference shows run-to-run peak variability, so neither run establishes
  a dependable reserve for streams. Backend JUnit: 1,997 tests, 0 failures/errors,
  15 skipped. Android, frontend, security, lint, RLS, image bootstrap and Alembic
  gates passed on both heads.
- **Pilot:** remains at 1536 MiB; no Compose recreation, Docker update, or service
  restart was performed. Rollout requires a separate evidence-backed operation.

## Residual risk / mass-test gate

Keep Fleet32 at **NO-GO** until Redis is measured with the intended 32-viewer profile
and Docker host aggregate memory. Both isolated 2048 MiB probes passed; one hit the
ceiling and one peaked at about 1.49 GiB. Use the maximum observed peak and host-level
measurements; do not treat the lower rerun as a guaranteed margin or stream capacity.
Redis eviction can still remove
application keys under pressure; slow subscribers, buffers and network recovery are
separate tests. An abrupt power loss is not covered by graceful restart validation.
