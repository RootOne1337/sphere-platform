export type StreamQualitySettings = { profile: 'auto' | 'detail' | 'economy'; max_fps: number | null; max_bitrate_bps: number | null };
export type StreamQualitySnapshot = {
  supported: boolean; protocol: 1; settings: StreamQualitySettings;
  active: null | { width: number; height: number; source_fps: number; codec_max_fps: number;
    target_fps: number; max_bitrate_bps: number; target_bitrate_bps: number; adaptation: 'source' | 'webrtc' | 'legacy_queue' };
};
const integer = (value: unknown, min: number, max: number): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
export function parseStreamQuality(value: unknown): StreamQualitySnapshot | null {
  if (!object(value) || typeof value.supported !== 'boolean' || value.protocol !== 1 || !object(value.settings)) return null;
  const s = value.settings;
  if (!['auto', 'detail', 'economy'].includes(String(s.profile))
    || s.max_fps !== null && !integer(s.max_fps, 1, 60)
    || s.max_bitrate_bps !== null && !integer(s.max_bitrate_bps, 100_000, 32_000_000)) return null;
  const a = value.active;
  if (a !== null && (!object(a) || !integer(a.width, 1, 8192) || !integer(a.height, 1, 8192)
    || !integer(a.source_fps, 1, 240) || !integer(a.codec_max_fps, 1, 60) || !integer(a.target_fps, 1, 60)
    || !integer(a.max_bitrate_bps, 1, 32_000_000) || !integer(a.target_bitrate_bps, 1, 32_000_000)
    || a.target_fps > a.source_fps || a.target_fps > a.codec_max_fps || a.target_bitrate_bps > a.max_bitrate_bps
    || !['source', 'webrtc', 'legacy_queue'].includes(String(a.adaptation)))) return null;
  return value as StreamQualitySnapshot;
}
export function qualityDraft(profile: StreamQualitySettings['profile'], fps: string, mbps: string): StreamQualitySettings | null {
  const max_fps = fps.trim() === '' ? null : Number(fps);
  const max_bitrate_bps = mbps.trim() === '' ? null : Math.round(Number(mbps) * 1_000_000);
  if (max_fps !== null && !integer(max_fps, 1, 60)
    || max_bitrate_bps !== null && !integer(max_bitrate_bps, 100_000, 32_000_000)) return null;
  return { profile, max_fps, max_bitrate_bps };
}
