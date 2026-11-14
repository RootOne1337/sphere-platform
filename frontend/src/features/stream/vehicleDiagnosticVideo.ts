const idPattern = /^[0-9a-f]{32}$/;
const hashPattern = /^[0-9a-f]{64}$/;
const epochPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const whole = (value: unknown, low: number, high: number) =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= low && value <= high;

export type DiagnosticVideoConfig = {
  id: string;
  scope: string;
  clip: string;
  job: string;
  captureEpoch: string;
  geometrySha256: string | null;
  width: number;
  height: number;
  beganAtMs: number;
};
type CaptureResult = {saved: boolean; retentionConfirmed: boolean; endedEarly: boolean};
export type DiagnosticVideoCapture = {stop(reason: string): Promise<CaptureResult>};
type ArchiveEntry = {
  runId: string;
  clip: string;
  beganAtMs: number;
  durationTicks90k: number;
  videoBytes: number;
  indexBytes: number;
  indexSha256: string;
  endedEarly: string | null;
  folder: FileSystemDirectoryHandle;
  marker: File;
};
const unsaved: CaptureResult = {saved: false, retentionConfirmed: false, endedEarly: false};
const captures = new WeakMap<Worker, DiagnosticVideoCapture>();

/** Save the existing incoming H.264 stream without encoding or sending it again. */
export function beginVehicleDiagnosticVideo(worker: Worker, config: DiagnosticVideoConfig): DiagnosticVideoCapture | null {
  if (captures.has(worker)) return null;
  let settle: (result: CaptureResult) => void;
  let timeout: ReturnType<typeof setTimeout> | null = null;
  let settled = false, stopping = false;
  const done = new Promise<CaptureResult>(resolve => { settle = resolve; });
  const finish = (result: CaptureResult) => {
    if (settled) return;
    settled = true;
    if (timeout !== null) clearTimeout(timeout);
    captures.delete(worker);
    worker.removeEventListener('message', receive);
    settle(result);
  };
  const receive = ({data}: MessageEvent) => {
    if (data?.type !== 'diagnostic_video_finalized' || data.id !== config.id) return;
    finish({saved: data.saved === true, retentionConfirmed: data.retentionConfirmed === true, endedEarly: !!data.endedEarly});
  };
  const capture = {
    stop(reason: string) {
      if (!settled && !stopping) {
        stopping = true;
        timeout = setTimeout(() => finish(unsaved), 10000);
        try { worker.postMessage({type: 'diagnostic_video_stop', id: config.id, reason}); }
        catch { finish(unsaved); }
      }
      return done;
    },
  };
  worker.addEventListener('message', receive);
  captures.set(worker, capture);
  try { worker.postMessage({type: 'diagnostic_video_start', config}); }
  catch { finish(unsaved); }
  return capture;
}

export function terminateTeachingRecorder(worker?: Worker) {
  if (!worker) return;
  const pending = captures.get(worker);
  if (pending) void pending.stop('connection_closed').finally(() => worker.terminate());
  else worker.terminate();
}

export async function listVehicleDiagnosticVideos(scope: string): Promise<ArchiveEntry[]> {
  if (!idPattern.test(scope)) return [];
  const root = await navigator.storage.getDirectory();
  const archive = await root.getDirectoryHandle('sphere-vehicle-video-' + scope)
    .catch(error => { if (error?.name === 'NotFoundError') return null; throw error; });
  if (!archive) return [];
  const iterable = archive as FileSystemDirectoryHandle & {values(): AsyncIterableIterator<FileSystemHandle>};
  const entries: ArchiveEntry[] = [];
  for await (const entry of iterable.values()) {
    if (entry.kind !== 'directory' || !idPattern.test(entry.name)) continue;
    try {
      const folder = await archive.getDirectoryHandle(entry.name);
      const marker = await (await folder.getFileHandle('COMPLETE')).getFile();
      if (marker.size > 2048) continue;
      const value = JSON.parse(await marker.text());
      if (value?.schema !== 'sphere-vehicle-video-v1' || value.runId !== entry.name
        || typeof value.clip !== 'string' || !idPattern.test(value.clip)
        || typeof value.job !== 'string' || !idPattern.test(value.job)
        || typeof value.captureEpoch !== 'string' || !epochPattern.test(value.captureEpoch)
        || value.captureEpoch === '00000000-0000-0000-0000-000000000000'
        || value.geometrySha256 != null && (typeof value.geometrySha256 !== 'string' || !hashPattern.test(value.geometrySha256))
        || !Number.isFinite(value.beganAtMs) || !Number.isFinite(new Date(value.beganAtMs).getTime())
        || value.beganAtMs < 0 || !Number.isFinite(value.endedAtMs) || value.endedAtMs < value.beganAtMs
        || !whole(value.width, 1, 8192) || !whole(value.height, 1, 8192)
        || Math.ceil(value.width / 16) * Math.ceil(value.height / 16) > 36864
        || !whole(value.frames, 1, 108000) || !whole(value.durationTicks90k, 0, 1801 * 90000)
        || !whole(value.videoBytes, 1, 512 * 1024 ** 2) || !whole(value.indexBytes, 1, 48 * 1024 ** 2)
        || [value.endedEarly, value.stopReason].some(item => item !== null && (typeof item !== 'string' || item.length > 128))
        || typeof value.indexSha256 !== 'string' || !hashPattern.test(value.indexSha256)) continue;
      entries.push({...value, folder, marker});
    } catch { /* In-progress or removed by another tab. */ }
  }
  return entries.sort((a, b) => b.beganAtMs - a.beganAtMs || b.runId.localeCompare(a.runId)).slice(0, 2);
}

export async function downloadVehicleDiagnosticVideo(entry: ArchiveEntry, kind: 'video' | 'index' | 'metadata') {
  const extension = kind === 'index' ? 'jsonl' : kind === 'metadata' ? 'json' : 'h264';
  const file = kind === 'metadata' ? entry.marker
    : await (await entry.folder.getFileHandle(kind === 'index' ? 'frames.jsonl' : 'video.h264')).getFile();
  if (kind !== 'metadata' && file.size !== (kind === 'index' ? entry.indexBytes : entry.videoBytes))
    throw Error('diagnostic_video_file_changed');
  if (kind === 'index') {
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    if (Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('') !== entry.indexSha256)
      throw Error('diagnostic_video_index_changed');
  }
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = `sphere-vehicle-${entry.runId}.${extension}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
