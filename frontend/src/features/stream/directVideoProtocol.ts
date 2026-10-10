/** A video experiment never borrows the echo-only SDP permission. No audio or input. */
export function readonlyVideoSdp(value: string, offer: boolean): boolean {
  if (new TextEncoder().encode(value).length > 32768) return false;
  const lines = value.split(/\r?\n/), sections: string[][] = [];
  for (const line of lines) {
    if (line.startsWith('m=')) sections.push([line]);
    else sections.at(-1)?.push(line);
  }
  const applications = sections.filter(s => s[0].startsWith('m=application '));
  const pictures = sections.filter(s => s[0].startsWith('m=video '));
  const fingerprints = lines.filter(line => line.startsWith('a=fingerprint:'));
  return lines[0] === 'v=0' && sections.length === 2 && applications.length === 1 && pictures.length === 1
    && applications[0][0].includes('UDP/DTLS/SCTP') && pictures[0][0].includes('UDP/TLS/RTP/SAVPF')
    && pictures[0].filter(line => ['a=sendonly', 'a=recvonly', 'a=sendrecv', 'a=inactive'].includes(line)).length === 1
    && pictures[0].includes(offer ? 'a=recvonly' : 'a=sendonly')
    && pictures[0].some(line => /^a=rtpmap:[0-9]+ H264\/90000$/i.test(line))
    && fingerprints.length >= 1 && fingerprints.length <= 3
    && fingerprints.every(line => /^a=fingerprint:sha-256 (?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}$/.test(line))
    && lines.filter(line => line.startsWith('a=candidate:')).length <= 64;
}

export interface DirectVideoBinding { captureEpoch: string; width: number; height: number }
export function parseVideoBinding(value: unknown, session: string): DirectVideoBinding | null {
  if (typeof value !== 'string' || value.length > 128) return null;
  const match = /^SV1 ([0-9a-f]{32}) ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}) ([1-9][0-9]{0,4}) ([1-9][0-9]{0,4})$/.exec(value);
  if (!match || match[1] !== session || match[2] === '00000000-0000-0000-0000-000000000000') return null;
  const width = Number(match[3]), height = Number(match[4]);
  if (width > 16384 || height > 16384 || Math.ceil(width / 16) * Math.ceil(height / 16) > 3600) return null;
  return { captureEpoch: match[2], width, height };
}
