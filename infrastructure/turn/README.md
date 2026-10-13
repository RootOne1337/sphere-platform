# Optional direct-transport relay

Позднейший срез: [прямой маршрут с ноутбука и восстановление запуска ввода](../../docs/audits/2026-10-13/DIRECT-INPUT-RECOVERY.md). Старые наблюдения ниже сохраняют собственные версии и время.

Текущий direct pilot: [наблюдение 13 октября](../../docs/audits/2026-10-13/DIRECT-SESSION-STABILITY.md). TURN остаётся выключенным; связь во всех NAT/WAN сетях не принята.

Status: deployment template, **not an installed public service**. The default
viewer without canary admission uses its existing WebSocket stream. The admitted
canaries, including APK63 on PH010/PH030, can use primary WebRTC video and native DataChannel touches, with
server video as a reserve. That live path currently negotiates host and public
STUN candidates; it does not consume this template's TURN credentials.

TURN admission currently covers the finite `sphere-probe-v2` DataChannel echo
diagnostic and the separately admitted `sphere-video-probe-v1` video diagnostic.
Neither diagnostic grants native input. The live `sphere-video-v1` protocol
rejects a relay grant. A successful diagnostic allocation therefore does not
establish a working relay path for ordinary viewing or control.

The image is pinned to the official coturn 4.18.0-r0 Linux amd64 manifest. This
compose file targets a Linux relay host, not Docker Desktop host networking. A
Tuna HTTPS website is not evidence of a reachable TURN endpoint.

## Configuration

Use a dedicated relay hostname with a valid TLS certificate. Provision three
private files readable by container UID 65534 and set their paths:

* `SPHERE_TURN_HOST`: the DNS hostname covered by the TLS certificate.
* `SPHERE_TURN_REST_KEY_FILE`: 64 lowercase hexadecimal characters, generated with
  a cryptographically secure random source; do not commit the file.
* `SPHERE_TURN_TLS_CHAIN_FILE`: PEM full certificate chain for that hostname.
* `SPHERE_TURN_TLS_KEY_FILE`: corresponding private key.

Startup rejects missing, expired, hostname-mismatched or key-mismatched TLS
material before starting coturn. This local check does not establish certificate
chain trust or public reachability; test both from the actual clients.

Configure the API through its existing secret delivery mechanism:

```text
DIRECT_PROBE_TURN_URLS=["turn:relay.example.net:3478?transport=udp","turns:relay.example.net:5349?transport=tcp"]
DIRECT_PROBE_TURN_SECRET=<the same private REST key>
DIRECT_PROBE_TURN_RELAY_ONLY=false
```

These settings alone do not enable diagnostics: the API canary flag and exact
device allowlist are still required. The temporary diagnostic web build uses
`NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY=true` and
`NEXT_PUBLIC_DIRECT_PROBE_RELAY=true`; remove its static STUN build setting.
Never place the REST master key in a `NEXT_PUBLIC_*` value. The API authenticates
the user and device, reserves the global device lease, then issues separate
browser and agent credentials valid for 120 seconds. Per-device issuance has a
15-second cooldown that survives closing the socket.

`all` allows ICE to try direct candidates and relay candidates. `relay` is for an
explicit diagnostic comparison; do not label its selected path as P2P. The
120-second credential lifetime is not a promise of immediate revocation of an
already authenticated allocation; allocation/refresh behavior needs its own
acceptance check.

Live relay support still needs an explicit credential renewal and ICE restart
contract across API, browser and APK. Do not pass these finite credentials to a
long-running live peer or increase their lifetime to hide missing renewal.
Validate continuity beyond credential expiry, revocation and reconnect before
admitting live relay traffic.

Open 3478 UDP/TCP, 5349 TCP, and UDP 49200–49327 on the relay host and its upstream
gateway. Configure `external-ip=PUBLIC/PRIVATE` in `turnserver.conf` if needed;
verify the mapped relay ports. The template blocks private/loopback/link-local
peer destinations and does not support relaying to LAN-only peers. Do not remove
these blocks to compensate for an incorrect public/NAT address.

Validate file permissions and deployment configuration, then start explicitly:

```sh
docker compose -f infrastructure/turn/compose.yml --profile direct-relay config --quiet
docker compose -f infrastructure/turn/compose.yml --profile direct-relay up -d
```

The template limits allocations, bandwidth, memory, threads, PIDs, descriptors,
temporary files and Docker log retention. These are initial admission limits,
not a measured production capacity. Do not expose this template without verifying
anonymous/wrong-key/expired-key denial, valid authentication, TLS identity, peer
denials, quotas, refresh behavior and selected-pair evidence from real clients.

## Acceptance and rollback

Run localhost, LAN and separate-network checks independently. Record selected ICE
pair, VPN route, connection success, RTT distribution, loss, resource plateau and
reconnect behavior. Existing canary direct-video/input checks do not accept WAN
relay behavior. Live relay renewal, native input ownership through relay,
authorization loss and long-session recovery require additional implementation
and tests; successful TURN authentication alone does not close those requirements.

The 12 October PH025 observation sent ICE checks from both peers without receiving
responses. It narrows the observed failure to connectivity checking, but does not
identify NAT, a firewall, VPN or an emulator bridge as the cause. An installed
public TURN service and a direct/relay comparison remain open. See the current
[stream observation](../../docs/operations/CURRENT-STATE.md).

To stop only this relay:

```sh
docker compose -f infrastructure/turn/compose.yml --profile direct-relay down
```

Disable the diagnostic flags/allowlist independently. Do not rotate the ordinary
APK, delete Docker volumes or disable the user's VPN as part of relay cleanup.

References: [WebRTC TURN](https://webrtc.org/getting-started/turn-server),
[coturn configuration](https://github.com/coturn/coturn/blob/master/examples/etc/turnserver.conf),
[coturn REST credentials](https://github.com/coturn/coturn/blob/master/README.turnserver).
