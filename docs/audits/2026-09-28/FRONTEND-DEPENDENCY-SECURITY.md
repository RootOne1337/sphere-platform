# Frontend dependency security remediation

**Reviewed:** 28 September 2026, Asia/Yekaterinburg<br />
**Scope:** `frontend/package.json`, `frontend/package-lock.json`, and the affected frontend test typing.<br />
**Change status:** source change for draft PR #19; no deploy, release, OTA publication, or device operation is included.

## Finding

The PR branch's frontend lockfile previously selected Next.js `15.5.13`. That
version is below the patched `15.5.24` release for two critical Next.js
advisories: [GHSA-2xp9-vwfh-vxw4](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4),
which concerns remote code execution when AVIF image optimization is used, and
[GHSA-p293-qw3h-jr36](https://github.com/vercel/next.js/security/advisories/GHSA-p293-qw3h-jr36),
which concerns Windows-hosted servers using the Pages or App Router without
Cache Components. The latter condition is specific to a Windows-hosted runtime;
the checked-in frontend Dockerfile uses `node:20-alpine`, so the advisory alone
does not establish that the deployed Sphere service was exposed. The live image
and configuration were not inspected during this source change.

The previous lockfile also resolved PostCSS `8.5.6` and Handlebars `4.7.8`.
PostCSS `8.5.6` was below the fixed releases for the
[source-map path traversal advisory](https://github.com/postcss/postcss/security/advisories/GHSA-r28c-9q8g-f849)
and its incomplete follow-up fix
([GHSA-fxqj-rqcc-2cmp](https://github.com/postcss/postcss/security/advisories/GHSA-fxqj-rqcc-2cmp)).
Handlebars `4.7.8` was affected by the critical
[AST type-confusion advisory](https://github.com/handlebars-lang/handlebars.js/security/advisories/GHSA-2w6w-674q-4c4q).
In this lockfile Handlebars is a **development-only** dependency of `ts-jest`;
that finding does not by itself prove exposure in the production request path.
The complete finding set and production/development reachability are evaluated
by npm against the actual lockfile rather than inferred from names alone.

When commit `2cf7e50` was pushed, GitHub's push response reported **145
Dependabot vulnerabilities on the default branch `main`**: 5 critical, 64 high,
63 moderate and 13 low. This is a repository/default-branch snapshot, not a
count for this PR's frontend lockfile; it may include alerts from multiple
manifests. The branch-local zero result below does not clear the default-branch
alerts. Review and remediation of the remaining alerts is a separate, broader
workstream; no merge was performed.

## Remediation

- Pin `next` and `eslint-config-next` to `15.5.26`, above the Next.js patched
  floor while retaining the existing 15.5 release line.
- Pin PostCSS to `8.5.28` and make the override follow that direct version, so
  Next.js and other consumers resolve the same patched PostCSS.
- Refresh the lockfile to patched compatible transitive releases, including
  Handlebars `4.7.9`.
- Adjust one `useDevices` test assertion to type Axios request parameters
  explicitly; the dependency type update made the prior implicit property
  access fail TypeScript checking. Runtime behavior is unchanged.

## Verification

| Check | Result |
| --- | --- |
| Frontend Jest | 41 suites, 306 tests passed. |
| TypeScript | `npm run type-check` passed. |
| npm audit | `npm audit` from `frontend/` reported 0 low/moderate/high/critical findings across the resolved frontend lockfile. |
| Local production build | `npm run build` exited `0` and generated all 30 static pages/routes. On this Windows host Next.js emitted a warning that it could not copy the route-group `page_client-reference-manifest.js` into `.next/standalone`; the file was absent from the source route directory, and the warning was also recorded on the earlier local build. This is not represented as a clean standalone trace. |
| GitHub CI, PR source | Full CI for `5c9e56c` passed: frontend `npm ci`, tests/types/build and standalone entrypoint; backend tests, lint/security/RLS, production image bootstrap and Alembic; Android build/unit tests. Preview deploy was skipped. |

The CI result proves the PR source build/test behavior at `5c9e56c`, including
the updated frontend lockfile. It does not prove that the production container
was rebuilt or deployed. The local Windows tracing warning remains a separate
environment-specific caveat; the Linux CI's standalone entrypoint check passed.

## Residual scope

This patch covers the frontend npm dependency graph. It does not claim that
the remaining GitHub Dependabot alerts on the default branch, Python/backend dependencies,
the Android Gradle graph, deployed images, or production runtime have been
cleared. Those scopes require their own current lockfile/image evidence. No
mass device test, server mutation, tunnel change, or APK release was performed.
