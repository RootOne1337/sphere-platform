/** Versioned binary video envelope. A header is evidence of capture identity,
 * not input readiness or proof that a browser has displayed a picture. */
export interface SphereFrameEnvelope {
  version: 1 | 2;
  timestampUs: number;
  captureEpoch: string | null;
  payload: Uint8Array;
}

const MAX_PAYLOAD_BYTES = 1024 * 1024;

export function parseSphereFrame(data: ArrayBuffer): SphereFrameEnvelope | null {
  if (data.byteLength <= 14) return null;
  const view = new DataView(data);
  const version = view.getUint8(0);
  if (version !== 1 && version !== 2) return null;
  const headerBytes = version === 2 ? 30 : 14;
  if (data.byteLength <= headerBytes || data.byteLength > headerBytes + MAX_PAYLOAD_BYTES ||
      view.getUint32(10, false) !== data.byteLength - headerBytes) return null;
  const timestampUs = Number(view.getBigInt64(2, false)) * 1000;
  if (!Number.isSafeInteger(timestampUs) || timestampUs < 0) return null;
  let captureEpoch: string | null = null;
  if (version === 2) {
    const bytes = new Uint8Array(data, 14, 16);
    if ((view.getUint8(1) & ~1) !== 0 || !bytes.some(byte => byte !== 0)) return null;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    captureEpoch = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return { version, timestampUs, captureEpoch, payload: new Uint8Array(data, headerBytes) };
}
