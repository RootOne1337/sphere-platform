/* Original received H264 only. This worker never modifies or delays decoded delivery for disk IO. */
'use strict';
let transformer, recording = null, command = Promise.resolve(), observedFrames = 0;
let externalCapture = false, lastEncodedHeartbeat = 0;
const encode = new TextEncoder();
const stamp = () => performance.timeOrigin + performance.now();
const validStamp = value => Number.isFinite(value) && value >= 0 && value <= Number.MAX_SAFE_INTEGER;
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
  if (!r.diagnostic) postMessage({ type: 'failed', reason });
}
function limit(r, reason) {
  r.accept = false; r.limit = reason;
  if (!r.diagnostic) postMessage({ type: 'limit_reached', reason });
}
function enqueue(r, bytes, write) {
  if (r.queuedBytes + bytes > 8 * 1024 * 1024 || r.queued >= 32) { failure(r, 'disk_queue_budget'); return false; }
  r.queuedBytes += bytes; r.queued++;
  r.queueHighWater = Math.max(r.queueHighWater,r.queuedBytes);
  r.tail = r.tail.then(async()=>{const began=stamp();await write();r.maxWriteMs=Math.max(r.maxWriteMs,stamp()-began);}).catch(() => {
    r.writeFailed = true; failure(r, 'recording_write_failed');
  }).finally(() => { r.queuedBytes -= bytes; r.queued--; });
  return true;
}
function frame(value) {
  const receivedAt = stamp();
  observedFrames++;
  if (receivedAt - lastEncodedHeartbeat >= (externalCapture?100:200)) {
    const meta = value.getMetadata();
    if (value.data.byteLength && meta.mimeType?.toLowerCase() === 'video/h264' && Number.isInteger(meta.rtpTimestamp)) {
      lastEncodedHeartbeat = receivedAt;
      postMessage({ type: 'encoded_heartbeat',receivedAtMs:lastEncodedHeartbeat });
    }
  }
  if (observedFrames === 1 || observedFrames % 60 === 0) {
    const meta = value.getMetadata();
    postMessage({ type: 'encoded_status', frames: observedFrames, kind: value.type,
      nal_types: [...nalTypes(new Uint8Array(value.data))], width: meta.width ?? null,
      height: meta.height ?? null, codec: meta.mimeType ?? null });
  }
  const r = recording;
  if (!r?.accept) return;
  if (!validStamp(receivedAt) || receivedAt < r.at || receivedAt < r.lastFrameAt) { failure(r, 'browser_clock_regressed'); return; }
  r.lastFrameAt = receivedAt;
  if (r.started && receivedAt - r.startedAt >= r.config.max_duration_ms || r.frames >= r.config.max_frames) { limit(r, 'duration_or_frame_limit'); return; }
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
      if (receivedAt - r.at > 10000) failure(r, 'idr_headers_timeout');
      return;
    }
    r.started = true; r.startedAt = receivedAt; r.ssrc = meta.synchronizationSource; r.firstRtp = r.lastRtp = timestamp; r.ticks = 0;
    if (!r.diagnostic) postMessage({ type: 'recording', id: r.id });
  } else {
    const delta = (timestamp - r.lastRtp + 0x100000000) % 0x100000000;
    if (!delta || delta > 90000) { failure(r, 'rtp_discontinuity'); return; }
    r.maxGapTicks=Math.max(r.maxGapTicks,delta);r.gaps25+=Number(delta>2250);r.gaps50+=Number(delta>4500);r.gaps100+=Number(delta>9000);
    r.gaps200+=Number(delta>18000);r.gaps500+=Number(delta>45000);
    r.gapHistogram[Math.min(1000,Math.ceil(delta/90))]++;
    r.ticks += delta; r.lastRtp = timestamp;
  }
  const data = value.data.slice(0), offset = r.bytes;
  const index = { index: r.frames, offset, bytes: size, rtp_timestamp: timestamp, relative_ticks_90k: r.ticks,
    worker_observed_at_ms: receivedAt, geometry_reported: knownGeometry, key: types.has(5), seekable: types.has(5) && types.has(7) && types.has(8), sha256: null };
  if (!enqueue(r, size, async () => {
    index.sha256 = await hash(data); await r.video.write(data);
    await r.index.write(encode.encode(JSON.stringify(index) + '\n'));
  })) return;
  r.bytes += size; r.frames++;
  if (r.frames % 300 === 0) void transformer.sendKeyFrameRequest().catch(() => {});
  if (!r.diagnostic && (r.frames % 30 === 0 || receivedAt-r.lastProgressAt>=1000)) {
    r.lastProgressAt=receivedAt;postMessage({ type: 'progress', frames: r.frames, bytes: r.bytes, seconds: r.ticks / 90000,
      capture_quality:quality(r) });
  }
}
function quality(r) {
  const seconds=(r.ticks??0)/90000,fps=seconds>0?Math.max(0,r.frames-1)/seconds:null;
  let p95GapMs=null;
  if(r.frames>1){const target=Math.ceil((r.frames-1)*.95);let count=0;
    for(let ms=0;ms<r.gapHistogram.length;ms++){count+=r.gapHistogram[ms];if(count>=target){p95GapMs=ms;break;}}}
  return {cadence_policy:'rtp-30fps-gap50-v1',received_encoded_fps:fps,target_fps:r.config.target_fps??null,measured_seconds:seconds,
    received_bitrate_bps:seconds>0?r.bytes*8/seconds:null,max_media_gap_ms:r.maxGapTicks/90,
    p95_media_gap_ms:p95GapMs,gaps_over_25ms:r.gaps25,gaps_over_50ms:r.gaps50,gaps_over_100ms:r.gaps100,
    gaps_over_200ms:r.gaps200,gaps_over_500ms:r.gaps500,disk_queue_high_water_bytes:r.queueHighWater,
    max_disk_write_ms:r.maxWriteMs,transcoding:false,synthetic_frames:0,
    cadence_30fps_confirmed:seconds>=3&&fps>=29.5&&r.gaps50===0,
    cadence_60fps_confirmed:seconds>=3&&fps>=59&&r.gaps25===0,
    source_render_quality_verified:false,android_capture_latency_known:false};
}
async function arm(config, receivedAt = stamp()) {
  if (!transformer || recording) throw Error('recorder_already_used');
  if (!validStamp(receivedAt)) throw Error('invalid_recorder_clock');
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
    if (entry.kind === 'directory' && ++count >= 100) throw Error('recording_library_limit');
  }
  try { await library.getDirectoryHandle(config.id); throw Error('recording_exists'); }
  catch (error) { if (error.name !== 'NotFoundError') throw error; }
  const directory = await library.getDirectoryHandle(config.id, { create: true });
  const r = await openCapture(config, directory, receivedAt);
  postMessage({ type: 'armed', id: r.id });
  void transformer.sendKeyFrameRequest().catch(() => {});
}
async function openCapture(config, directory, receivedAt, diagnostic = null) {
  const r = recording = { id: config.id, config, directory, at: receivedAt, accept: false, started: false, diagnostic,
    frames: 0, bytes: 0, events: 0, inputBytes: 0, pending: new Map(), closed: false,
    lastInputAt: receivedAt, lastFrameAt: receivedAt, lastSourceInputAt: null,
    queued: 0, queuedBytes: 0, queueHighWater:0,maxWriteMs:0,maxGapTicks:0,gaps25:0,gaps50:0,gaps100:0,gaps200:0,gaps500:0,
    gapHistogram:new Uint32Array(1001),lastProgressAt:0,
    tail: Promise.resolve(), failure: null };
  const create = async name => (await directory.getFileHandle(name, { create: true })).createWritable();
  r.video = await create('video.h264'); r.index = await create('frames.jsonl');
  if (!diagnostic) r.input = await create('inputs.jsonl');
  r.readyAt = stamp();
  if (!validStamp(r.readyAt) || r.readyAt < r.at) throw Error('browser_clock_regressed');
  r.accept = true;
  return r;
}
function input(event, receivedAt = stamp()) {
  const r = recording;
  if (!r || r.stopping || r.diagnostic) return;
  if (!event || !['submitted','receipt','closed'].includes(event.stage) || !validStamp(event.at_ms)
    || !Number.isSafeInteger(event.sequence) || !Number.isSafeInteger(event.gesture)
    || !Number.isSafeInteger(event.action) || !Number.isSafeInteger(event.pointer_id)) { failure(r, 'invalid_input_journal'); return; }
  if (!validStamp(receivedAt) || receivedAt < r.lastInputAt
    || r.lastSourceInputAt !== null && event.at_ms < r.lastSourceInputAt) { failure(r, 'browser_clock_regressed'); return; }
  // Page emission and worker receipt are different observations. File-system
  // setup/command queues may finish after both. Keep the page timestamp intact
  // rather than clamping it to a later worker start or pretending it was an ACK.
  event = { ...event, source_at_ms: event.at_ms, at_ms: receivedAt };
  r.lastInputAt = receivedAt; r.lastSourceInputAt = event.source_at_ms;
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
  if (r?.diagnostic) { await stopDiagnostic(r.id, reason).catch(() => {}); return; }
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
  const finalizedAt = stamp();
  if (!validStamp(finalizedAt) || finalizedAt < r.at || finalizedAt < r.lastInputAt || finalizedAt < r.lastFrameAt) r.failure ||= 'browser_clock_regressed';
  const manifest = { schema: 'sphere-browser-teaching-v2', id: r.id, config: r.config,
    started_at_ms: r.at, worker_ready_at_ms: r.readyAt, finalized_at_ms: finalizedAt, frames: r.frames, events: r.events, files,
    media_duration_ticks_90k: r.ticks ?? 0, ended_at_limit: r.limit ?? null,
    observed_encoded_frames: observedFrames,
    capture_quality:quality(r),
    clock: { media: 'rtp_90000_relative', browser: 'performance_timeOrigin_plus_now',
      input: 'worker_message_received_performance_timeOrigin_plus_now', source_input: 'page_performance_timeOrigin_plus_now',
      native: 'android_uptime_ms_in_receipts', android_to_browser_mapping: null },
    complete: !r.failure, failure: r.failure, release_confirmed: confirmed && r.closed };
  const write = async (name, text) => { const f = await (await r.directory.getFileHandle(name,{create:true})).createWritable(); await f.write(text); await f.close(); };
  const text = JSON.stringify(manifest, null, 2) + '\n';
  await write('manifest.json', text);
  if (!r.failure) await write('COMPLETE', JSON.stringify({ manifest_sha256: await hash(encode.encode(text)) }) + '\n');
  postMessage({ type: 'finalized', id: r.id, manifest });
}

// One optional video writer per account in this browser. The old two clips
// are retained until a new video has closed and has a verified index.
const diagnosticCap = 512 * 1024 ** 2;
const diagnosticId = /^[0-9a-f]{32}$/;
async function diagnosticEntries(archive, currentId) {
  const completed = [];
  for await (const entry of archive.values()) {
    if (entry.kind !== 'directory' || !diagnosticId.test(entry.name) || entry.name === currentId) continue;
    const folder = await archive.getDirectoryHandle(entry.name);
    let meta = null;
    try {
      const marker = await (await folder.getFileHandle('COMPLETE')).getFile();
      if (marker.size <= 2048) meta = JSON.parse(await marker.text());
    } catch (error) { if (!(error instanceof SyntaxError) && error.name !== 'NotFoundError') throw error; }
    if (meta?.schema === 'sphere-vehicle-video-v1' && meta.runId === entry.name && Number.isFinite(meta.beganAtMs))
      completed.push({ id: entry.name, at: meta.beganAtMs });
    else await archive.removeEntry(entry.name, { recursive: true });
  }
  return completed.sort((a, b) => b.at - a.at || b.id.localeCompare(a.id));
}
async function diagnosticLock(scope) {
  return new Promise((resolve, reject) => {
    void navigator.locks.request('sphere-vehicle-video-' + scope, { ifAvailable: true }, lock => {
      if (!lock) { reject(Error('diagnostic_writer_busy')); return; }
      return new Promise(release => resolve(release));
    }).catch(reject);
  });
}
async function startDiagnostic(config, receivedAt) {
  const { id, scope, clip, job, captureEpoch, geometrySha256, width, height, beganAtMs } = config ?? {};
  if (!transformer || recording || ![id, scope, clip, job].every(v => typeof v === 'string' && diagnosticId.test(v))
    || typeof captureEpoch !== 'string' || !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(captureEpoch)
    || captureEpoch === '00000000-0000-0000-0000-000000000000'
    || geometrySha256 !== null && (typeof geometrySha256 !== 'string' || !/^[0-9a-f]{64}$/.test(geometrySha256))
    || !Number.isInteger(width) || width < 1 || width > 8192 || !Number.isInteger(height) || height < 1 || height > 8192
    || !validStamp(beganAtMs) || !navigator.locks) throw Error('diagnostic_capture_unavailable');
  const release = await diagnosticLock(scope);
  try {
    const root = await navigator.storage.getDirectory();
    const archive = await root.getDirectoryHandle('sphere-vehicle-video-' + scope, { create: true });
    const completed = await diagnosticEntries(archive);
    for (const entry of completed.slice(2)) await archive.removeEntry(entry.id, { recursive: true });
    try { await archive.getDirectoryHandle(id); throw Error('diagnostic_capture_exists'); }
    catch (error) { if (error.name !== 'NotFoundError') throw error; }
    const directory = await archive.getDirectoryHandle(id, { create: true });
    await openCapture({ id, width, height, max_duration_ms: 1800000, max_frames: 108000, max_bytes: diagnosticCap },
      directory, receivedAt, { archive, release, clip, job, captureEpoch, geometrySha256, beganAtMs });
    void transformer.sendKeyFrameRequest().catch(() => {});
  } catch (error) {
    if (recording?.diagnostic?.release === release) {
      const r = recording; recording = null;
      await Promise.allSettled([r.video?.abort(), r.index?.abort()]);
    }
    release();
    throw error;
  }
}
async function stopDiagnostic(id, reason) {
  const r = recording;
  if (!r?.diagnostic || r.id !== id || r.stopping) return;
  r.stopping = true; r.accept = false;
  const { archive, release, clip, job, captureEpoch, geometrySha256, beganAtMs } = r.diagnostic;
  let saved = false, retentionConfirmed = false;
  try {
    await r.tail;
    const closed = await Promise.allSettled([r.video.close(), r.index.close()]);
    if (closed.some(result => result.status === 'rejected')) throw Error('diagnostic_close_failed');
    const read = async name => (await r.directory.getFileHandle(name)).getFile();
    const video = await read('video.h264'), index = await read('frames.jsonl');
    if (!r.frames || !r.bytes || r.bytes !== video.size || !index.size || index.size > 48 * 1024 ** 2
      || r.writeFailed) throw Error('diagnostic_no_video_or_incomplete_write');
    const marker = { schema: 'sphere-vehicle-video-v1', runId: id, clip, job, captureEpoch, geometrySha256,
      beganAtMs, endedAtMs: stamp(), width: r.config.width, height: r.config.height, frames: r.frames,
      durationTicks90k: r.ticks ?? 0, videoBytes: video.size, indexBytes: index.size,
      indexSha256: await hash(await index.arrayBuffer()), endedEarly: r.failure ?? r.limit ?? null,
      stopReason: typeof reason === 'string' ? reason.slice(0, 128) : null };
    const done = await (await r.directory.getFileHandle('COMPLETE', { create: true })).createWritable();
    try { await done.write(JSON.stringify(marker)); await done.close(); }
    catch (error) { await done.abort().catch(() => {}); throw error; }
    saved = true;
    const older = await diagnosticEntries(archive, id);
    for (const entry of older.slice(1)) await archive.removeEntry(entry.id, { recursive: true });
    retentionConfirmed = true;
  } finally {
    try { if (!saved) await archive.removeEntry(id, { recursive: true }); }
    finally {
      recording = null; release();
      postMessage({ type: 'diagnostic_video_finalized', id, saved, retentionConfirmed, endedEarly: r.failure ?? r.limit ?? null });
    }
  }
}
self.onmessage = ({ data }) => {
  // Capture arrival before waiting for an earlier command or OPFS promises.
  const receivedAt = stamp();
  command = command.then(async () => {
    if (data?.type === 'arm') await arm(data.config, receivedAt);
    else if (data?.type === 'input') input(data.event, receivedAt);
    else if (data?.type === 'stop') await stop(data.confirmed === true, data.reason);
    else if (data?.type === 'external_capture') { externalCapture = data.enabled === true; lastEncodedHeartbeat = 0; }
    else if (data?.type === 'diagnostic_video_start') {
      try { await startDiagnostic(data.config, receivedAt); }
      catch { postMessage({ type: 'diagnostic_video_finalized', id: data.config?.id, saved: false }); }
    }
    else if (data?.type === 'diagnostic_video_stop') await stopDiagnostic(data.id, data.reason).catch(() => {});
  }).catch(error => {
    const known=['recorder_already_used','invalid_recording_config','invalid_recording_budget','recording_library_limit','recording_exists','invalid_recorder_clock','browser_clock_regressed'];
    const reason=known.includes(error?.message)?error.message:error?.name==='QuotaExceededError'?'recording_storage_full':['NotAllowedError','SecurityError'].includes(error?.name)?'recording_storage_denied':recording?'recorder_command_failed':'recorder_start_failed';
    if(recording)failure(recording,reason);else postMessage({type:'failed',reason});
  });
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
