# Frontend session boundaries

Reviewed 8 September 2026. This describes the implemented browser session flow;
backend authorization remains mandatory for every request. See AUD-48–52 in the
[audit report](../audits/2026-09-05/AUDIT-REPORT.md) for evidence and open risks.

`Providers` mounts private pages only after initialization has completed and both
the access token and user identity exist. `/login` is the exact public route.
There is no frontend authentication bypass flag. A redirect alone is insufficient:
private hooks and streams must remain unmounted while navigation is pending.

The access token lives in Zustand memory. The backend sets an HttpOnly refresh
cookie; `sphere_refresh_token` in localStorage remains a fallback for environments
where cookies are unavailable. This fallback is readable by JavaScript and is not
equivalent to HttpOnly storage. Preventing XSS and reviewing credential exposure in
other browser stores remain necessary.

Login begins a new session version. Login and MFA responses update token and user
atomically only if that attempt is still current. Leaving the MFA flow invalidates
the attempt. Each API call captures its version synchronously; responses and retries
from a retired version are rejected. Already executed server actions cannot be
undone by this browser check and still require server-side idempotency.

Startup and concurrent 401 handlers share one refresh request per version, with a
five-second transport timeout. Rotation preserves the version for the same user and
organization. Each original request can retry at most once. A refresh returning a
different identity fails closed. A genuine refresh failure clears the session and
requires login; a failure from an old session cannot clear a newer one.

Each session/identity/role gets a distinct React Query client before its page is
rendered. Unmount cancels queries and clears the retired client. A late completion
cannot populate the next client's cache. This does not establish cleanup of every
independent Zustand store, DOM widget, browser history entry or downloaded file.

Sign out captures the current Bearer and refresh fallback, immediately clears local
access, records logout intent, navigates to login and sends a raw logout request.
It does not invoke the API refresh interceptor. On network failure the login page
states that server revocation was not confirmed. A subsequent login is protected
from that old request's failure. Missing or invalid Bearer cannot establish server
revocation even when the endpoint returns 204 to delete a cookie.

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
