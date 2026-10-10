# Build provenance in the operator UI

**Updated:** 30 September 2026<br>
**Scope:** source/build traceability for the Sphere web frontend and backend API.

## What the operator sees

The authenticated application header shows `WEB <sha>` and `API <sha>`:

- `WEB` is the Git revision embedded in the Next.js bundle at build time.
- `API` is returned by `GET /api/v1/health/build` from the running backend image.
- Revisions are shortened to eight hexadecimal characters for display. The API
  returns its validated full Git SHA so support can compare it exactly.
- `unknown` means the image did not report a valid Git SHA. `no metadata` means
  the revision endpoint returned HTTP 404 (for example, an older backend).
  `unavailable` means the revision lookup failed, including network errors,
  authorization errors or server errors. These are metadata states, not API health
  checks, and none is treated as a successful version match. The tooltip explains
  the distinction; 403/503 are not silently classified as an unsupported endpoint.
- Revision metadata refreshes once per minute. A failed refresh is not used to
  assert a revision mismatch from an older cached response.

The endpoint intentionally exposes only service name, semantic API version, and
the validated source SHA. It does not return environment variables, container
IDs, hostnames, credentials, or deployment configuration. A Git SHA is public
source metadata, not a secret.

## How revisions enter the images

Both Dockerfiles accept `BUILD_SHA`. The frontend builder maps it to
`NEXT_PUBLIC_BUILD_SHA` before `next build`, so Next.js embeds the value in the
client bundle. The backend stores it as `SPHERE_BUILD_SHA`; the build-info route
validates it at request time. Preview CI passes `github.sha` to both images and
builds the backend from repository root with `backend/Dockerfile`, matching the
Dockerfile's `COPY backend/`, `COPY alembic/`, and `COPY agent-config/` inputs.

For a local production-image build from a clean checkout, pass the exact full
commit SHA to Compose:

```powershell
$env:BUILD_SHA = (git rev-parse HEAD).Trim()
docker compose -f docker-compose.yml -f docker-compose.production.yml build backend frontend
```

If `BUILD_SHA` is omitted, both images report `unknown`. Do not manually stamp a
dirty working tree with `HEAD`: the revision identifies the commit, not any
uncommitted changes layered into a local image.

## Verification procedure

1. Confirm the image build job used the intended commit and passed `BUILD_SHA`.
2. Read `GET /api/v1/health/build` on the target API. Compare its full `revision`
   with the intended commit SHA.
3. Open the target web application and compare the `WEB` value in the header
   with the same commit. A mismatch means the frontend and backend are from
   different builds; it is visible rather than silently assumed healthy.
4. Record the target URL, image tags/digests, both returned revisions, and check
   time in the deployment receipt. A passing source test alone does not prove a
   deployment or an Android-device rollout.

## Current rollout boundary

The local read-only frontend preview `3012` was rebuilt on 30 September with a
known frontend SHA. Its pilot backend `40357ca` returns HTTP 404 for this metadata
endpoint while `/health` returns 200. Backend provenance, production rollout and
remote-device acceptance remain open. Older images do not acquire the endpoint
without rebuilding them. See [current state](CURRENT-STATE.md) for the dated receipt.
