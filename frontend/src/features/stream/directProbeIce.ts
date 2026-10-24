/** Immutable diagnostic build profile; never accepts an endpoint from signaling or a device. */
export class DirectProbeConfigurationError extends Error {
  constructor() { super('invalid_controlled_stun'); }
}

export type DirectProbeIceProfile = 'host' | 'controlled-stun' | 'public-stun' | 'turn';

export function directProbeIceConfig(url = ''): {
  profile: DirectProbeIceProfile; iceServers: RTCIceServer[];
} {
  if (url === '') return { profile: 'host', iceServers: [] };
  // A single explicitly selected, documented public diagnostic service; never a default/fallback.
  if (url === 'stun:stun.cloudflare.com:3478')
    return { profile: 'public-stun', iceServers: [{ urls: url }] };
  // Otherwise one canonical RFC1918 IPv4 endpoint, without DNS, credentials or transport options.
  const match = typeof url === 'string' && /^stun:([0-9.]+):([0-9]+)$/.exec(url);
  if (!match) throw new DirectProbeConfigurationError();
  const parts = match[1].split('.');
  if (parts.length !== 4 || parts.some(part => !/^(0|[1-9][0-9]{0,2})$/.test(part) || Number(part) > 255))
    throw new DirectProbeConfigurationError();
  const [first, second] = parts.map(Number);
  const port = Number(match[2]);
  if (!(first === 10 || first === 172 && second >= 16 && second <= 31 || first === 192 && second === 168)
    || !/^[1-9][0-9]{3,4}$/.test(match[2]) || port < 1024 || port > 65535)
    throw new DirectProbeConfigurationError();
  return { profile: 'controlled-stun', iceServers: [{ urls: url }] };
}
