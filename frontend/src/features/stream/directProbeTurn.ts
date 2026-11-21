/** Only the authenticated server supplies this temporary configuration. No persistent storage. */
export interface DirectProbeTurnGrant {
  urls: string[]; username: string; credential: string; ttl_ms: 120000; policy: 'all' | 'relay';
}

export function validTurnUrl(value: unknown): value is string {
  if (typeof value !== 'string' || value.length > 320) return false;
  const match = /^(turn|turns):([a-z0-9.-]{1,253}):([1-9][0-9]{0,4})\?transport=(udp|tcp)$/.exec(value);
  if (!match || match[0] !== value) return false;
  const [, scheme, host, port, transport] = match;
  if (Number(port) > 65535 || scheme === 'turns' && transport !== 'tcp') return false;
  const parts = host.split('.');
  if (/^[0-9.]+$/.test(host)) {
    if (parts.length !== 4 || parts.some(p => !/^(0|[1-9][0-9]{0,2})$/.test(p) || Number(p) > 255)) return false;
    const [first, second] = parts.map(Number);
    return first !== 0 && first !== 127 && first < 224 && !(first === 169 && second === 254);
  }
  return parts.length >= 2 && /^[a-z][a-z0-9-]*$/.test(parts.at(-1)!) &&
    parts.every(p => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(p));
}

export function parseTurnReady(value: unknown, protocol = 'sphere-probe-v2'): { session: string; configuration: RTCConfiguration } | null {
  if (!value || typeof value !== 'object') return null;
  const ready = value as Record<string, unknown>;
  if (Object.keys(ready).sort().join() !== 'ice,protocol,session_id,type' || ready.type !== 'direct_probe_ready' ||
    ready.protocol !== protocol || typeof ready.session_id !== 'string' || ready.session_id.length !== 32 || !/^[0-9a-f]{32}$/.test(ready.session_id) ||
    !ready.ice || typeof ready.ice !== 'object') return null;
  const ice = ready.ice as Record<string, unknown>;
  if (Object.keys(ice).sort().join() !== 'credential,policy,ttl_ms,urls,username' ||
    !Array.isArray(ice.urls) || ice.urls.length < 1 || ice.urls.length > 3 || !ice.urls.every(validTurnUrl) ||
    new Set(ice.urls).size !== ice.urls.length || ice.ttl_ms !== 120000 || !['all', 'relay'].includes(ice.policy as string) ||
    typeof ice.username !== 'string' || ice.username.length !== 51 || !new RegExp(`^[1-9][0-9]{9}:${ready.session_id}:browser$`).test(ice.username) ||
    typeof ice.credential !== 'string' || ice.credential.length !== 28 || !/^[A-Za-z0-9+/]{27}=$/.test(ice.credential)) return null;
  return { session: ready.session_id, configuration: { bundlePolicy: 'max-bundle',
    iceTransportPolicy: ice.policy as RTCIceTransportPolicy,
    iceServers: [{ urls: [...ice.urls], username: ice.username, credential: ice.credential }] } };
}
