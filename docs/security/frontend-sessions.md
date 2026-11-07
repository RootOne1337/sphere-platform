# Frontend session boundaries

Original review: 8 September 2026. The relevant source paths were rechecked on
1 November 2026. This describes the implemented browser session flow;
backend authorization remains mandatory for every request. See AUD-48–52 in the
[audit report](../audits/2026-09-05/AUDIT-REPORT.md) for evidence and open risks.

`Providers` mounts private pages only after initialization has completed and both
the access token and user identity exist. `/login` is the exact public route.
There is no frontend authentication bypass flag. A redirect alone is insufficient:
private hooks and streams must remain unmounted while navigation is pending.

The access token lives in Zustand memory. The backend sets an HttpOnly refresh
cookie and also returns a refresh token in the response body. When present, the
frontend stores it as `sphere_refresh_token` in localStorage for fallback transport,
even when cookies are available. This copy is readable by JavaScript and is not
equivalent to HttpOnly storage. Preventing XSS and reviewing credential exposure in
other browser stores remain necessary.

Login begins a new session version. Login and MFA responses update token and user
atomically only if that attempt is still current. Leaving the MFA flow invalidates
the attempt. Calls through the shared `api` Axios instance capture their version
synchronously; its responses and retries from a retired version are rejected. Raw
Axios calls such as login and logout have their own guards, not that interceptor.
Already executed server actions cannot be
undone by this browser check and still require server-side idempotency.

Startup and concurrent 401 handlers share one refresh request per version, with a
five-second transport timeout. Rotation preserves the version for the same user and
organization. Eligible requests through that interceptor can retry at most once;
auth operations are excluded except `GET /auth/capabilities`. A refresh returning a
different identity fails closed. A non-transient error, malformed response or
identity change clears the current session; a network failure, timeout,
408, 429 or 5xx preserves the current identity and credentials while rejecting the
operation. A later explicit request may try refresh again. A failure from an old
session cannot clear a newer one. In particular, the implementation treats HTTP 4xx
other than 408 and 429 as non-transient, even if the status is not 401.

The server selects a nonempty refresh cookie before `X-Refresh-Token`, and the JSON
body only if neither exists. A stale cookie can therefore override a valid fallback
header; the server does not retry another source when the selected token is rejected.
If SQL rotation succeeds but its response is lost, the browser may retain the old
credential; a later retry can receive 401 and clear the session. User refresh has no
device-style lost-response recovery receipt. A transient browser error alone does
not reveal whether server rotation committed.

Each session/identity/role gets a distinct React Query client before its page is
rendered. Unmount cancels queries and clears the retired client. A late completion
cannot populate the next client's cache. This does not establish cleanup of every
independent Zustand store, DOM widget, browser history entry or downloaded file.
The user role in the browser is refreshed with a successful token response; a
server-side role edit does not itself push a new user object into every open tab.
For routes using `get_current_user`, the backend reloads the active user and RBAC
checks that database role rather than relying on the stale role claim in the JWT.
Capabilities and visual state have their own refresh timing and do not replace
server checks.

Sign out captures the current Bearer and refresh fallback, immediately clears local
access, records logout intent, navigates to login and sends a raw logout request.
It does not invoke the API refresh interceptor. On network failure the login page
states that server revocation was not confirmed. A subsequent login is protected
from that old request's failure. Missing or invalid Bearer cannot establish server
revocation even when the endpoint returns 204 to delete a cookie.
The handler uses cookie before header for the refresh being revoked. Its JWT decoder
checks the signature and required `sub`, `jti` and `type` claims but skips expiry
validation; the handler also needs `exp`. It does not check that `type` is `access`
or compare subject/tenant with the independently supplied refresh token. The service
blacklists that access JTI when unexpired and revokes the selected refresh token if
found; this is not family-wide logout and does not prove every other token is revoked.

The `sphere_signed_out` marker prevents automatic cookie restoration after explicit
logout. When storage is blocked, the current document retains the boundary in memory
and can use cookie transport, but this intent cannot persist across a full reload.
The backend serializes consumption of each refresh row (AUD-52). Concurrent
Set-Cookie responses, refresh-family revocation and cross-tab coordination
need further testing. Never describe an offline logout as confirmed remote revocation.

Run `npm ci --ignore-scripts`, `npm run type-check`, `npx --no-install jest --runInBand`
and `npm run build` from `frontend` on Node 24. CI repeats these checks on Linux and
checks that the standalone server entry point was packaged. On Windows, if a host
npm configuration overrides the OS, use `npm ci --os=win32 --cpu=x64 --include=optional
--ignore-scripts` instead; do not change global npm settings for this repository.

The tests use real React/JSDOM, Zustand, React Query and Axios interceptors with
controlled adapters. They do not start a server or prove browser cookie/CORS/SameSite
behavior. The recorded Windows Next build exits 0 but warns about a missing traced
manifest and an inferred parent workspace root. Build exit status alone is not a
standalone deployment or APK-to-server runtime check. Frontend coverage thresholds
are unchanged; ordinary Jest invocation does not establish whole-frontend coverage.

Source scope: [`store.ts`](../../frontend/lib/store.ts), [`api.ts`](../../frontend/lib/api.ts),
[`providers.tsx`](../../frontend/app/providers.tsx), [auth router](../../backend/api/v1/auth/router.py),
[auth service](../../backend/services/auth_service.py) and
[`get_current_user`](../../backend/core/dependencies.py). Test examples include
[`refresh-races`](../../frontend/__tests__/session/refresh-races.test.tsx),
[`logout`](../../frontend/__tests__/session/logout.test.tsx),
[rotation](../../tests/production/test_session_rotation.py) and
[logout API](../../tests/production/test_session_logout.py). These tests were not
rerun for this source review; actual browser, ingress, roles and deployment remain unverified.
