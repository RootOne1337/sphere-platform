# Build provenance in the operator UI

**Updated:** 29 September 2026<br>
**Scope:** source/build traceability for the Sphere web frontend and backend API.

## What the operator sees

The authenticated application header shows `WEB <sha>` and `API <sha>`:

- `WEB` is the Git revision embedded in the Next.js bundle at build time.
- `API` is returned by `GET /api/v1/health/build` from the running backend image.
- Revisions are shortened to eight hexadecimal characters for display. The API
  returns its validated full Git SHA so support can compare it exactly.
- `unknown` means the image was built without a valid Git SHA. `unavailable`
  means the browser could not reach the API endpoint. Neither state is treated
  as a successful version match.

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

The implementation is source-level until CI builds images that contain these
fields and an operator verifies them on the target runtime. No live preview,
production service, APK, or remote Android device is updated by this change.
Older running images will not acquire a build stamp without rebuilding them.
