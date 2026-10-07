# Docker storage: runtime data, image history and retention

Date: 2026-10-07. Operator timezone: UTC+5. Installed UI/API: `a41c4e6`.
This extends [the completed host window](HOST-STORAGE-FOLLOWUP.md), not its
writer attribution. The host disk incident remains OPEN.

## Measurements before cleanup

At 11:09:53 UTC, C: free was 26,318,794,752 B. The Docker data VHDX was
234,731,077,632 B (234.73 decimal GB / 218.61 GiB), not a measured 251 GB.
The second Docker WSL VHDX was 142,606,336 B. File length and filesystem
allocation inside the guest are different measurements.

Metadata-only `du -x -k` of Docker's data filesystem measured:

| Scope | Allocated KiB | Meaning |
| --- | ---: | --- |
| Entire Docker data directory | 193,841,400 | Guest allocated files, not host VHD length |
| containerd store | 185,725,952 | Image content and unpacked snapshots |
| containerd compressed content | 29,773,360 | Content-addressed image blobs |
| containerd overlayfs snapshots | 155,912,008 | Unpacked layers, shared with images/cache |
| Docker volumes | 7,535,340 | All projects' named volume data |
| Container directories | 329,428 | Logs and container metadata, all 46 containers |
| Sphere Android uploaded logs | 139,652 | Fourteen device directories |
| Sphere MinIO data | 104 | Object store plus metadata |

`pg_database_size(current_database())` returned 16,694,631 B for Sphere's
database. This is not the full PostgreSQL volume or WAL allocation.

Docker Engine `system df` reported 222 images / 186.7 GB, 46 containers /
318.1 MB, 68 volumes / 7.25 GB and 767 cache records / 84.42 GB. Images
and cache overlap: these values MUST NOT be added. The 14 running containers
are different from the 14 Android devices. Neither count represents a disk
allocation limit.

## Does the stream save every frame?

[VideoTransport](../../../backend/websocket/video_transport.py) publishes binary
video through Redis Pub/Sub; it does not use an append-only Redis stream/list
or a filesystem archive. [VideoStreamQueue](../../../backend/websocket/video_queue.py)
holds at most 50 frames / 8 MiB per queue and expires stale picture chains at
200 ms. These are RAM bounds per queue, not a global fleet RAM guarantee.

[Native screenshots](../../../backend/services/native_screenshot.py) use a
separate bounded PNG capture and attempt Android temporary-file cleanup.
[Task screenshots](../../../backend/services/screenshot_storage.py) use MinIO.
The current 104 KiB object-store allocation contradicts the hypothesis of
hundreds of gigabytes of persisted task frames in this local instance.
It does not prove an eternal object-retention guarantee or cover every
installed APK version's private storage.

## Confirmed retention omissions

The previous [ownership planner](../../../scripts/pilot/plan_owned_image_retention.py)
only recognised three runtime repository names and one test repository name.
Six other explicitly named Sphere web-test repositories were excluded. Each
historical test image can have about 2.09 GB of unique unpacked image data.
Retaining two images for each new one-off test name would retain every test
forever, even when no container uses it.

The corrected policy:

1. Uses exact runtime and web-test repository allowlists; no `sphere-*` wildcard.
2. Requires every tag to contain a resolvable source commit from this checkout.
3. Excludes untagged, foreign, mixed-ownership and noncommit aliases.
4. Protects dependencies of ALL running AND stopped containers.
5. Protects the installed reviewed source independently of age.
6. Keeps at least two images per runtime repository.
7. Keeps at least two images across the explicitly owned web-test pool.
8. Still writes a read-only plan; application needs fresh container/tag/ID checks.

The test pool contains only these reviewed names:

| Repository | Locally observed source revision |
| --- | --- |
| sphere-ui-inspection-recovery-web-tests | c1a6e79a75221c45a71160a21bc91c48b22ef5ae |
| sphere-ui-inspection-web-tests | 0b3518999573a25320e0171686e323f2fd581ad0 |
| sphere-organization-action-access-web-tests | 922f479d29d5eee833e8b66ddfc4aea2401e0e9d |
| sphere-device-action-access-web-tests | 81d065a90919c1ad60312f81cb4f821e034ad501 |
| sphere-session-capabilities-web-tests | 00d5ad8b072c490662c3c8242ac3b3b47e49b1be |
| sphere-ota-publication-web-tests | 77fca37847590bef526ae5becdf7b1986d5b15ea |
| sphere-vpn-control-web-tests | a2c4f02972d090b0707dc3f7ae48e803810a35be |

No ownership is inferred for `mini-factory-race`, `ruflo-mcp-bridge`, dangling
images, other Sphere-like names or foreign aliases. No volume is a candidate.

## First finite cleanup: completed

The original allowlist produced 34 single-tag candidates. Before each ordinary
`docker image rm <immutable-config-ID>` application, all 46 container epochs
and the candidate's tags/creation time were checked again. No force removal,
container/volume removal, daemon restart or broad prune was used.

11:13:08–11:13:53 UTC:

| Measurement | Before | After |
| --- | ---: | ---: |
| Guest filesystem used bytes | 201,708,032,000 | 199,086,292,992 |
| Image count | 222 | 188 |
| All container count | 46 | 46 |
| Running container count | 14 | 14 |

Guest space reclaimed: **2,621,739,008 B / 2.442 GiB**. All container epochs
and the explicit previous UI `b50d6ae` / API `114775a` rollback images were
preserved. Private receipt: `.local-pilot/studio-followup-20261007/retention-1110-receipt.json`.
This is NOT 2.442 GiB returned to C:; the VHDX length stayed unchanged.

## Cache experiment: no reclaim, not counted as success

Five exact cache IDs for unused immutable `npm ci --no-audit --no-fund`
results were inspected: reclaimable=true, shared=false, last-used "3 days ago".
Literal-ID filtered `buildx prune` returned `Total: 0B` for each. All five
records remained. A single-ID retry with explicit reserved-space=0 also
returned 0 B. No broad selector, `--all` or image/volume deletion followed.

Installed versions: Engine 29.2.1, Buildx v0.32.1-desktop.1, BuildKit v0.27.1.
Read-only boolean filters `shared=false`, `inuse=false`, `mutable=false`
returned zero records although matching raw rows exist. This discrepancy
needs diagnosis; a zero-row selector is not proof that no cache is reclaimable.
The Desktop builder config already has GC enabled / defaultKeepStorage=20GB.
Its 84.42 GB aggregate cache includes image-shared storage, so that number
alone does not prove the configured private-cache target is violated.

Private exact-ID receipts are retained under `.local-pilot/studio-followup-20261007/`.
Official [cache inspection](https://docs.docker.com/reference/cli/docker/buildx/du/),
[prune selectors](https://docs.docker.com/reference/cli/docker/buildx/prune/) and
[GC policy](https://docs.docker.com/build/cache/garbage-collection/)
were checked on 2026-10-07. Installed-driver observations take precedence over
an untested interpretation of the current documentation.

## Remaining production work and host recovery boundary

The current uploaded-log allocation is small, but
[the upload route](../../../backend/api/v1/logs/router.py) rotates the CURRENT
DAY file at about 50 MiB and retains older files for 30 days. The comment
"per device" is not a total-directory quota: a device could retain around
30 daily files. Global quotas and cross-worker rotation locking are explicitly
absent. This is a future fleet-capacity risk, not the proven writer of today's
8.517 GiB host loss.

The screenshot URL's one-hour validity is not object deletion. A tested object
retention policy, total log quota, cross-worker coordination and real storage
budget metrics remain required before accepting a 500–1000-device deployment.

The completed eight-hour host window lost 8.517 GiB while VHDX measurements
stayed constant. Writes inside a constant-size VHD can still cause Windows
VSS copy-on-write growth. VSS/FileIO attribution is unavailable to the current
non-elevated collector; it is not zero. The already requested finite elevated
collector has not produced a new report as of this audit.

Returning unused guest blocks to Windows may require offline compaction.
Microsoft documents [compact vdisk](https://learn.microsoft.com/windows-server/administration/windows-commands/compact-vdisk)
for detached/read-only dynamically expanding disks. Do not compact a mounted
live Docker VHD, zero-fill the guest on a nearly full C:, change sparse flags,
reset Docker, delete volumes or shrink VSS without a reviewed procedure.
Offline compaction requires a separate service outage and administrator access;
it has not been performed in this incident stage.

## Validation

The planner's focused suite: **18 passed** with `--noconftest`; Ruff and mypy
passed. Tests cover shared test-pool retention, stopped dependencies, current
source, runtime rollback retention, unknown/mixed aliases and changed epochs.
This does not claim a full backend test run or resolved disk writer attribution.
