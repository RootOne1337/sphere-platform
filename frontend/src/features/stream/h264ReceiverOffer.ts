/** Older level31 sources retain the ordinary offer and their exact codec format. */
export function needsHigherH264ReceiveLevel(profile: string | null | undefined): boolean {
  return typeof profile === 'string' && /^42[ce]0[0-9a-f]{2}$/i.test(profile)
    && [32, 40, 41, 42, 50, 51, 52].includes(parseInt(profile.slice(-2), 16));
}

/** Raise H.264 receive level only after this browser confirms decoding it.
 * Only constrained-baseline fmtp changes; ICE, DTLS, sections and payload IDs stay intact.
 */
export async function h264ReceiverOffer(offer: RTCSessionDescriptionInit, size?: { width: number; height: number }): Promise<RTCSessionDescriptionInit> {
  if (!offer.sdp || !size || !Number.isInteger(size.width) || !Number.isInteger(size.height)
    || size.width < 1 || size.height < 1 || size.width > 8192 || size.height > 8192
    || typeof navigator.mediaCapabilities?.decodingInfo !== 'function') return offer;
  const blocks = Math.ceil(size.width / 16) * Math.ceil(size.height / 16);
  const levels = [[41, 8192, 245760], [42, 8704, 522240], [50, 22080, 589824], [51, 36864, 983040], [52, 36864, 2073600]];
  const selected = levels.find(([, picture, perSecond]) => blocks <= picture && blocks * 60 <= perSecond);
  if (!selected) return offer;
  const profile = `42e0${selected[0].toString(16)}`;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const supported = await Promise.race([
      navigator.mediaCapabilities.decodingInfo({ type: 'webrtc', video: {
        contentType: `video/H264;profile-level-id=${profile};packetization-mode=1`,
        width: size.width, height: size.height, bitrate: 32_000_000, framerate: 60,
      } }).then(value => value.supported === true),
      new Promise<false>(resolve => { timer = setTimeout(() => resolve(false), 500); }),
    ]);
    if (!supported) return offer;
    const h264 = new Set([...offer.sdp.matchAll(/^a=rtpmap:(\d+) H264\/90000\r?$/gim)].map(match => match[1]));
    const sdp = offer.sdp.replace(/^a=fmtp:(\d+) ([^\r\n]+)$/gm, (line, payload: string, params: string) => {
      if (!h264.has(payload) || !/(?:^|;)\s*packetization-mode=1(?:;|$)/.test(params)
        || !/(?:^|;)\s*level-asymmetry-allowed=1(?:;|$)/.test(params)) return line;
      return line.replace(/(profile-level-id=)42e0[0-9a-f]{2}/i, `$1${profile}`);
    });
    return { type: offer.type, sdp };
  } catch { return offer; }
  finally { if (timer !== undefined) clearTimeout(timer); }
}
