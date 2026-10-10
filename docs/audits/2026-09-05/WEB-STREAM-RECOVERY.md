# AUD-123 · recover the web viewer after network loss

**High · Device Stream reconnect and visible state · 14 September 2026.**

## Reproduction

The active `/stream` page uses `frontend/components/sphere/DeviceStream.tsx`.
Its reconnect callback recreated `attempt = 0` on every socket close, so the
documented backoff was always 500 ms. A remote close with code 1000 suppressed
reconnect even while the user continued viewing. An open but silent socket had
no application deadline. Cleanup left the retry timer scheduled.

Four tests against the original component fail: consecutive failures should
increase delay; a server normal close should recover; an open socket missing
server pings should recover; unmount should remove every retry timer. Three
terminal access/device rejection tests already pass.

## Fix and affected files

`frontend/components/sphere/DeviceStream.tsx` now owns one socket generation,
retry timer and watchdog. Failures back off from 500 ms to 15 seconds with jitter
and continue while the viewer remains mounted. Only actual server traffic resets
the backoff. Local cleanup cancels timers and prevents stale callbacks from
resurrecting a viewer. Remote code 1000 can reconnect; access/device codes
4001/4003/4004 remain terminal until the input/token changes.

The watchdog bounds handshake silence to approximately 15 seconds and established
socket silence to approximately 30 seconds, checked every five seconds. Backend
viewer pings arrive every ten seconds; lack of screen motion alone is not treated
as a network failure. The UI covers stale pixels with connection/retry/error text
and marks the stream live only when a decoder frame is rendered. Disconnected
pointer events do not send on a closed socket.

Regression: `frontend/__tests__/stream/reconnect.test.tsx` retains all seven
scenarios. All 25 frontend test suites / 208 tests pass; TypeScript passes.

## Residual risk and acceptance boundary

These tests exercise the component with a controlled socket and decoder. Web 6dea6b4 is deployed to the isolated pilot. Actual browser decoding and
reconnection after Android, server and common-ingress faults have now been
[observed in the same tab](NETWORK-RECOVERY-NATIVE.md), without F5 or another Start
click. Common-ingress recovery exposed the separate Android delay AUD-124. An expired or
rejected token relies on the existing authentication flow supplying a new token.
A browser cannot recover a changed public origin automatically; use a stable
origin for deployment. This change does not provide an independent second ingress.
