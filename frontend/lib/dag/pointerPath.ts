export type PointerPath = { schema_version: 1; frame_width: number; frame_height: number;
  points: { t_ms: number; action: 0 | 1 | 2; x: number; y: number }[] };
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const integer = (n: unknown): n is number => typeof n === 'number' && Number.isSafeInteger(n);
const keys = (v: object, names: string[]) => Object.keys(v).length === names.length && names.every(k => Object.hasOwn(v, k));
/** Mirrored by backend/schemas/pointer_path.py and APK's TimedPointerPath parser. */
export function validPointerPath(value: unknown): value is PointerPath {
  if (!object(value) || !keys(value, ['schema_version','frame_width','frame_height','points']) || value.schema_version !== 1) return false;
  const {frame_width: w,frame_height: h,points} = value;
  if (!integer(w) || !integer(h) || w < 1 || h < 1 || w > 16384 || h > 16384
    || !Array.isArray(points) || points.length < 2 || points.length > 4096) return false;
  let previous = 0;
  for (let i = 0; i < points.length; i++) {
    const p: unknown = points[i];
    if (!object(p) || !keys(p,['t_ms','action','x','y']) || !integer(p.t_ms) || !integer(p.action) || !integer(p.x) || !integer(p.y)
      || p.t_ms < previous || p.t_ms > 60000 || i === 0 && p.t_ms !== 0
      || p.action !== (i === 0 ? 0 : i === points.length-1 ? 1 : 2)
      || p.x < 0 || p.y < 0 || p.x >= w || p.y >= h) return false;
    previous = p.t_ms;
  }
  // All admitted keys and values are ASCII (fixed keys + bounded integers).
  return JSON.stringify(value).length <= 256*1024;
}
