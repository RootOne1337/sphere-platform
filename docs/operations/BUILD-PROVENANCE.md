# Build provenance in the operator UI

**Updated:** 16 October 2026<br>
**Scope:** source/build traceability for the Sphere web frontend and backend API.

## Trusted local frontend delivery

The maintainer can now run frontend regressions, build a Linux runtime image and
install that image locally without starting hosted Actions or exporting another
`image.tar.gz`. This is an explicit local execution path; it never fabricates an
Actions run ID. The default hosted archive admission remains separate.

1. Commit and push the intended source to the existing trusted branch. Run
   `python -m scripts.pilot.local_ci --sha <full-sha> --profiles frontend --node <node24-path> --publish`.
   The executor checks a detached source snapshot, the installed dependency lock,
   Jest results, transport/container probes and TypeScript. It posts
   `Sphere Local / Frontend regressions` to that exact GitHub commit and reads the
   status back. Production packaging is not implied by this status.
2. Run `python -m scripts.pilot.package_local_web --source <full-sha> --execution <local-receipt-path>
   --output <fresh-.local-pilot-directory> --node <node24-path>` on one line.
   Packaging validates the successful local test report and its current GitHub
   status, then builds from canonical Git bytes with Linux dependencies and a
   pinned Node image. Windows native modules are not copied into the image.
   The actual immutable image is tested through a read-only container on a
   temporary loopback port; all static page routes and advertised JS/CSS assets
   must pass. The probe removes its own container. No live UI is replaced here.
3. Plan with `python -m scripts.pilot.install_reviewed_web --artifact <directory>
   --source <full-sha> --expected-image-id <independently-checked-image-id> --local-execution`.
   Use the same command with `--apply` only when installing. The installer rechecks
   local evidence, image identity and complete Compose configuration, preserves
   other containers, API and OTA catalog, and retains the prior UI image for
   rollback. Local mode performs no Docker archive load/export or cache deletion.
4. Check the real browser after installation. HTTP pages/assets do not prove
   hydration, authentication, WebRTC or Android input. Publish a separately scoped
   delivery result with the installed UI/API/APK revisions and runtime evidence.

Local reports remain under `.local-pilot`; raw logs, credentials and browser
sessions are not uploaded as public CI evidence. A result is attached to the
commit actually tested, rather than copied to every subsequent documentation
commit. This path does not yet claim migration of every workflow, automatic
execution on every push, public fork support or complete cloud/Linux test parity.

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

## Historical rollout boundary: 30 September

The local read-only frontend preview `3012` was rebuilt on 30 September with a
known frontend SHA. Its pilot backend `40357ca` returns HTTP 404 for this metadata
endpoint while `/health` returns 200. Backend provenance, production rollout and
remote-device acceptance remain open. Older images do not acquire the endpoint
without rebuilding them. See [current state](CURRENT-STATE.md) for the dated receipt.
