/* Original received H264 only. This worker never modifies or delays decoded delivery for disk IO. */
'use strict';
let transformer, recording = null, command = Promise.resolve(), observedFrames = 0;
const encode = new TextEncoder();
const stamp = () => performance.timeOrigin + performance.now();
const hash = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
function nalTypes(bytes) {
  const found = new Set();
  for (let i = 0; i + 3 < bytes.length; i++) {
    if (bytes[i] || bytes[i + 1]) continue;
    const start = bytes[i + 2] === 1 ? i + 3 : bytes[i + 2] === 0 && bytes[i + 3] === 1 ? i + 4 : -1;
    if (start >= 0 && start < bytes.length) { found.add(bytes[start] & 31); i = start; }
  }
  return found;
}
function failure(r, reason) {
  if (r.failure) return;
  r.failure = reason; r.accept = false;
  postMessage({ type: 'failed', reason });
}
function limit(r, reason) {
  r.accept = false; r.limit = reason;
  postMessage({ type: 'limit_reached', reason });
}
function enqueue(r, bytes, write) {
  if (r.queuedBytes + bytes > 8 * 1024 * 1024 || r.queued >= 32) { failure(r, 'disk_queue_budget'); return false; }
  r.queuedBytes += bytes; r.queued++;
  r.queueHighWater = Math.max(r.queueHighWater,r.queuedBytes);
  r.tail = r.tail.then(async()=>{const began=stamp();await write();r.maxWriteMs=Math.max(r.maxWriteMs,stamp()-began);}).catch(() => failure(r, 'recording_write_failed')).finally(() => { r.queuedBytes -= bytes; r.queued--; });
  return true;
}
function frame(value) {
  observedFrames++;
  if (observedFrames === 1 || observedFrames % 60 === 0) {
    const meta = value.getMetadata();
    postMessage({ type: 'encoded_status', frames: observedFrames, kind: value.type,
      nal_types: [...nalTypes(new Uint8Array(value.data))], width: meta.width ?? null,
      height: meta.height ?? null, codec: meta.mimeType ?? null });
  }
  const r = recording;
  if (!r?.accept) return;
  if (r.started && stamp() - r.startedAt >= r.config.max_duration_ms || r.frames >= r.config.max_frames) { limit(r, 'duration_or_frame_limit'); return; }
  const meta = value.getMetadata();
  const knownGeometry = meta.width === r.config.width && meta.height === r.config.height;
  // Chromium reports 0x0 for delta frames. Only an already bound SPS/IDR may
  // establish geometry; a newly reported size or keyframe must still match.
  const omittedGeometry = (meta.width === 0 || meta.width === undefined) && (meta.height === 0 || meta.height === undefined);
  if (meta.mimeType?.toLowerCase() !== 'video/h264'
    || !knownGeometry && !(omittedGeometry && (r.started || value.type === 'delta'))) {
    failure(r, 'encoded_geometry_or_codec_changed'); return;
  }
  const timestamp = meta.rtpTimestamp;
  if (!Number.isInteger(timestamp) || timestamp < 0 || timestamp > 0xffffffff) { failure(r, 'rtp_clock_unavailable'); return; }
  const size = value.data.byteLength;
  if (!size || size > 2 * 1024 * 1024) { failure(r, 'invalid_access_unit_size'); return; }
  if (r.bytes + size > r.config.max_bytes) { limit(r, 'byte_limit'); return; }
  const view = new Uint8Array(value.data), types = nalTypes(view);
  if (!types.size) { failure(r, 'annex_b_required'); return; }
  if (omittedGeometry && (types.has(5) || types.has(7) || types.has(8))) { failure(r, 'keyframe_geometry_unavailable'); return; }
  if (!Number.isInteger(meta.synchronizationSource) || r.started && meta.synchronizationSource !== r.ssrc) {
    failure(r, 'rtp_source_changed'); return;
  }
  if (!r.started) {
    if (!(types.has(5) && types.has(7) && types.has(8))) {
      if (stamp() - r.at > 10000) failure(r, 'idr_headers_timeout');
      return;
    }
    r.started = true; r.startedAt = stamp(); r.ssrc = meta.synchronizationSource; r.firstRtp = r.lastRtp = timestamp; r.ticks = 0;
    postMessage({ type: 'recording', id: r.id });
  } else {
    const delta = (timestamp - r.lastRtp + 0x100000000) % 0x100000000;
    if (!delta || delta > 90000) { failure(r, 'rtp_discontinuity'); return; }
    r.maxGapTicks=Math.max(r.maxGapTicks,delta);r.gaps200+=Number(delta>18000);r.gaps500+=Number(delta>45000);
    r.ticks += delta; r.lastRtp = timestamp;
  }
  const data = value.data.slice(0), offset = r.bytes;
  const index = { index: r.frames, offset, bytes: size, rtp_timestamp: timestamp, relative_ticks_90k: r.ticks,
    worker_observed_at_ms: stamp(), geometry_reported: knownGeometry, key: types.has(5), seekable: types.has(5) && types.has(7) && types.has(8), sha256: null };
  if (!enqueue(r, size, async () => {
    index.sha256 = await hash(data); await r.video.write(data);
    await r.index.write(encode.encode(JSON.stringify(index) + '\n'));
  })) return;
  r.bytes += size; r.frames++;
  if (r.frames % 300 === 0) void transformer.sendKeyFrameRequest().catch(() => {});
  if (r.frames % 30 === 0 || stamp()-r.lastProgressAt>=1000) {
    r.lastProgressAt=stamp();postMessage({ type: 'progress', frames: r.frames, bytes: r.bytes, seconds: r.ticks / 90000,
      capture_quality:quality(r) });
  }
}
function quality(r) {
  const seconds=(r.ticks??0)/90000,fps=seconds>0?Math.max(0,r.frames-1)/seconds:null;
  return {received_encoded_fps:fps,target_fps:r.config.target_fps??null,measured_seconds:seconds,
    received_bitrate_bps:seconds>0?r.bytes*8/seconds:null,max_media_gap_ms:r.maxGapTicks/90,
    gaps_over_200ms:r.gaps200,gaps_over_500ms:r.gaps500,disk_queue_high_water_bytes:r.queueHighWater,
    max_disk_write_ms:r.maxWriteMs,transcoding:false,synthetic_frames:0,
    cadence_30fps_confirmed:seconds>=3&&fps>=29.5&&r.gaps200===0,
    source_render_quality_verified:false,android_capture_latency_known:false};
}
async function arm(config) {
  if (!transformer || recording) throw Error('recorder_already_used');
  if (!config || !/^[0-9a-f]{32}$/.test(config.id) || !/^[0-9a-f]{32}$/.test(config.storage_scope)
    || !Number.isInteger(config.width) || !Number.isInteger(config.height)
    || config.width < 1 || config.height < 1 || config.width > 8192 || config.height > 8192) throw Error('invalid_recording_config');
  config = { ...config, max_duration_ms: config.max_duration_ms ?? 120000, max_bytes: config.max_bytes ?? 512*1024*1024, max_frames: config.max_frames ?? 7200 };
  if (!Number.isInteger(config.max_duration_ms) || config.max_duration_ms < 1000 || config.max_duration_ms > 600000
    || !Number.isInteger(config.max_bytes) || config.max_bytes < 1024 || config.max_bytes > 2*1024*1024*1024
    || !Number.isInteger(config.max_frames) || config.max_frames < 1 || config.max_frames > 36000) throw Error('invalid_recording_budget');
  const root = await navigator.storage.getDirectory();
  const library = await root.getDirectoryHandle('sphere-teaching-' + config.storage_scope, { create: true });
  let count = 0;
  for await (const entry of library.values()) {
    if (entry.kind === 'directory' && ++count >= 20) throw Error('recording_library_limit');
  }
  try { await library.getDirectoryHandle(config.id); throw Error('recording_exists'); }
  catch (error) { if (error.name !== 'NotFoundError') throw error; }
  const directory = await library.getDirectoryHandle(config.id, { create: true });
  const r = recording = { id: config.id, config, directory, at: stamp(), accept: false, started: false,
    frames: 0, bytes: 0, events: 0, inputBytes: 0, pending: new Map(), closed: false,
    queued: 0, queuedBytes: 0, queueHighWater:0,maxWriteMs:0,maxGapTicks:0,gaps200:0,gaps500:0,lastProgressAt:0,
    tail: Promise.resolve(), failure: null };
  const create = async name => (await directory.getFileHandle(name, { create: true })).createWritable();
  r.video = await create('video.h264'); r.index = await create('frames.jsonl'); r.input = await create('inputs.jsonl');
  r.accept = true;
  postMessage({ type: 'armed', id: r.id });
  void transformer.sendKeyFrameRequest().catch(() => {});
}
function input(event) {
  const r = recording;
  if (!r || r.stopping) return;
  if (!event || !['submitted','receipt','closed'].includes(event.stage) || !Number.isFinite(event.at_ms)
    || !Number.isSafeInteger(event.sequence) || !Number.isSafeInteger(event.gesture)
    || !Number.isSafeInteger(event.action) || !Number.isSafeInteger(event.pointer_id)) { failure(r, 'invalid_input_journal'); return; }
  if (event.cancelled_pointers !== undefined && (event.stage !== 'closed' || !Array.isArray(event.cancelled_pointers)
    || event.cancelled_pointers.length > 3 || new Set(event.cancelled_pointers).size !== event.cancelled_pointers.length
    || event.cancelled_pointers.some(id => !Number.isInteger(id) || id < 0 || id > 2)
    || !Number.isSafeInteger(event.device_uptime_ms) || event.device_uptime_ms < 0)) { failure(r, 'invalid_native_cancel_journal'); return; }
  if (event.stage === 'submitted') {
    if (r.pending.has(event.sequence) || r.pending.size > 1) { failure(r, 'input_order_invalid'); return; }
    r.pending.set(event.sequence, event);
  } else if (event.stage === 'receipt') {
    const submitted = r.pending.get(event.sequence);
    if (!submitted || submitted.action !== event.action || submitted.gesture !== event.gesture || submitted.pointer_id !== event.pointer_id
      || !['alive','applied'].includes(event.outcome)) { failure(r, 'input_receipt_invalid'); return; }
    r.pending.delete(event.sequence);
  } else r.closed = event.outcome === 'closed';
  const data = encode.encode(JSON.stringify(event) + '\n');
  if (++r.events > 40000 || (r.inputBytes += data.length) > 8 * 1024 * 1024) { failure(r, 'input_journal_budget'); return; }
  enqueue(r, data.length, () => r.input.write(data));
}
async function stop(confirmed, reason) {
  const r = recording;
  if (!r) { postMessage({type:'finalized',id:null,manifest:{complete:false,failure:reason||'recorder_not_started'}}); return; }
  if (r.stopping) return;
  r.stopping = true; r.accept = false;
  if (!confirmed || !r.closed || r.pending.size || !r.started || !r.frames || reason) r.failure ||= reason || 'input_or_video_unconfirmed';
  await r.tail;
  for (const file of [r.video,r.index,r.input]) { try { await file?.close(); } catch { r.failure ||= 'file_close_failed'; } }
  const read = async name => (await r.directory.getFileHandle(name)).getFile();
  const files = {};
  for (const name of ['frames.jsonl','inputs.jsonl']) {
    const file = await read(name); files[name] = { bytes: file.size, sha256: await hash(await file.arrayBuffer()) };
  }
  files['video.h264'] = { bytes: (await read('video.h264')).size, integrity: 'sha256_per_access_unit_in_frames_jsonl' };
  const manifest = { schema: 'sphere-browser-teaching-v2', id: r.id, config: r.config,
    started_at_ms: r.at, finalized_at_ms: stamp(), frames: r.frames, events: r.events, files,
    media_duration_ticks_90k: r.ticks ?? 0, ended_at_limit: r.limit ?? null,
    observed_encoded_frames: observedFrames,
    capture_quality:quality(r),
    clock: { media: 'rtp_90000_relative', browser: 'performance_timeOrigin_plus_now',
      native: 'android_uptime_ms_in_receipts', android_to_browser_mapping: null },
    complete: !r.failure, failure: r.failure, release_confirmed: confirmed && r.closed };
  const write = async (name, text) => { const f = await (await r.directory.getFileHandle(name,{create:true})).createWritable(); await f.write(text); await f.close(); };
  const text = JSON.stringify(manifest, null, 2) + '\n';
  await write('manifest.json', text);
  if (!r.failure) await write('COMPLETE', JSON.stringify({ manifest_sha256: await hash(encode.encode(text)) }) + '\n');
  postMessage({ type: 'finalized', id: r.id, manifest });
}
self.onmessage = ({ data }) => {
  command = command.then(async () => {
    if (data?.type === 'arm') await arm(data.config);
    else if (data?.type === 'input') input(data.event);
    else if (data?.type === 'stop') await stop(data.confirmed === true, data.reason);
  }).catch(() => { if (recording) failure(recording,'recorder_command_failed'); else postMessage({type:'failed',reason:'recorder_start_failed'}); });
};
self.onrtctransform = event => {
  if (transformer) return;
  transformer = event.transformer;
  const stream = new TransformStream({ transform(value, controller) {
    try { frame(value); } catch { if (recording) failure(recording,'encoded_frame_failed'); }
    controller.enqueue(value);
  }});
  transformer.readable.pipeThrough(stream).pipeTo(transformer.writable).catch(() => { if(recording) failure(recording,'encoded_stream_closed'); });
  postMessage({ type: 'attached' });
};
