# AdminCN-inspired Sphere interface study

**Updated:** 29 September 2026. **Primary integration:** [Sphere Platform PR #19](https://github.com/RootOne1337/sphere-platform/pull/19), branch `codex/enterprise-audit-20260905`. It changes the existing `frontend/` application and preserves its API, authentication, routes, and business operations. The PR is not deployed to the live site.

The separate concept preview at `127.0.0.1:4177` remains a local research artifact with synthetic records. It is not the main site and does not call Sphere API, stream, OTA, or Android commands. To review the primary frontend build from this checkout, use the local production preview at `http://127.0.0.1:3011` while its server is running; the browser QA screenshots below are from that build with browser-only synthetic API/WebSocket fixtures.

For the current operator review, `http://127.0.0.1:3012/devices` serves the same local production build through a temporary read-only same-machine proxy. It permits read requests needed by the UI and blocks state-changing API calls; do not use it to validate delete, reboot, task launch, or other mutations. Data visible there comes from the already-running local backend and must be treated as real organization data. This preview is not the live site and does not publish or deploy changes.

## Primary frontend QA screenshots

- [Dashboard, 1440 × 1000](screenshots/primary-dashboard-fixture-1440x1000.png)
- [Device registry, 1440 × 1000](screenshots/primary-devices-fixture-1440x1000.png)
- [Device registry, 390 × 844](screenshots/primary-devices-fixture-390x844.png)
- [Infrastructure monitoring, 1440 × 1000](screenshots/primary-monitoring-fixture-1440x1000.png)
- [Infrastructure monitoring, 390 × 844](screenshots/primary-monitoring-fixture-390x844.png)
- [System logs, 1440 × 1000](screenshots/primary-logs-fixture-1440x1000.png)
- [System logs, 390 × 844](screenshots/primary-logs-fixture-390x844.png)
- [Task queue, 1440 × 1000](screenshots/primary-tasks-fixture-1440x1000.png)

Fixture values demonstrate layout and control wiring. They are not real device records or evidence of live backend/device behavior. Monitoring was tested against a malformed fixture response to confirm it fails visibly without a client-side crash. The log-clearing interaction was intercepted by a browser-only mock; no backend logs were deleted.

## Research record and concept preview

The design comparison, AdminCN/Studio Admin source revisions, official demos, integration boundaries, and license notes are documented in [CONCEPTS-RU.md](CONCEPTS-RU.md). The three-concept preview at `127.0.0.1:4177/sphere/concepts` remains isolated from the main Sphere frontend; it is useful for design comparison only.

The production implementation recreated Sphere-owned layout patterns and did not copy AdminCN or Studio Admin source/assets. Third-party attribution and the complete checked-in AdminCN MIT notice are retained in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). The separate Shadcn Studio website-license mismatch is documented in the research record.
