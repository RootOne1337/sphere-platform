/* Original received H264 only. This worker never modifies or delays decoded delivery for disk IO. */
'use strict';
let transformer, recording = null, command = Promise.resolve();
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
function enqueue(r, bytes, write) {
  if (r.queuedBytes + bytes > 8 * 1024 * 1024 || r.queued >= 32) { failure(r, 'disk_queue_budget'); return false; }
  r.queuedBytes += bytes; r.queued++;
  r.tail = r.tail.then(write).catch(() => failure(r, 'recording_write_failed')).finally(() => { r.queuedBytes -= bytes; r.queued--; });
  return true;
}
function frame(value) {
  const r = recording;
  if (!r?.accept) return;
  if (stamp() - r.at > 120000 || r.frames >= 7200) { failure(r, 'recording_duration_limit'); return; }
  const meta = value.getMetadata();
  if (meta.mimeType?.toLowerCase() !== 'video/h264' || meta.width !== r.config.width || meta.height !== r.config.height) {
    failure(r, 'encoded_geometry_or_codec_changed'); return;
  }
  const timestamp = meta.rtpTimestamp;
  if (!Number.isInteger(timestamp) || timestamp < 0 || timestamp > 0xffffffff) { failure(r, 'rtp_clock_unavailable'); return; }
  const size = value.data.byteLength;
  if (!size || size > 2 * 1024 * 1024 || r.bytes + size > 512 * 1024 * 1024) { failure(r, 'recording_byte_limit'); return; }
  const view = new Uint8Array(value.data), types = nalTypes(view);
  if (!types.size) { failure(r, 'annex_b_required'); return; }
  if (!r.started) {
    if (!(types.has(5) && types.has(7) && types.has(8))) {
      if (stamp() - r.at > 10000) failure(r, 'idr_headers_timeout');
      return;
    }
    r.started = true; r.firstRtp = r.lastRtp = timestamp; r.ticks = 0;
    postMessage({ type: 'recording', id: r.id });
  } else {
    const delta = (timestamp - r.lastRtp + 0x100000000) % 0x100000000;
    if (!delta || delta > 90000) { failure(r, 'rtp_discontinuity'); return; }
    r.ticks += delta; r.lastRtp = timestamp;
  }
  const data = value.data.slice(0), offset = r.bytes;
  const index = { index: r.frames, offset, bytes: size, rtp_timestamp: timestamp, relative_ticks_90k: r.ticks,
    worker_observed_at_ms: stamp(), key: types.has(5), sha256: null };
  if (!enqueue(r, size, async () => {
    index.sha256 = await hash(data); await r.video.write(data);
    await r.index.write(encode.encode(JSON.stringify(index) + '\n'));
  })) return;
  r.bytes += size; r.frames++;
  if (r.frames % 30 === 0) postMessage({ type: 'progress', frames: r.frames, bytes: r.bytes, seconds: r.ticks / 90000 });
}
async function arm(config) {
  if (!transformer || recording) throw Error('recorder_already_used');
  if (!config || !/^[0-9a-f]{32}$/.test(config.id) || !/^[0-9a-f]{32}$/.test(config.storage_scope)
    || !Number.isInteger(config.width) || !Number.isInteger(config.height)
    || config.width < 1 || config.height < 1 || config.width > 8192 || config.height > 8192) throw Error('invalid_recording_config');
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
    queued: 0, queuedBytes: 0, tail: Promise.resolve(), failure: null };
  const create = async name => (await directory.getFileHandle(name, { create: true })).createWritable();
  r.video = await create('video.h264'); r.index = await create('frames.jsonl'); r.input = await create('inputs.jsonl');
  r.accept = true;
  postMessage({ type: 'armed', id: r.id });
  void transformer.sendKeyFrameRequest().catch(() => {});
}
function input(event) {
  const r = recording;
  if (!r?.accept) return;
  if (!event || !['submitted','receipt','closed'].includes(event.stage) || !Number.isFinite(event.at_ms)
    || !Number.isSafeInteger(event.sequence) || !Number.isSafeInteger(event.gesture)
    || !Number.isSafeInteger(event.action) || !Number.isSafeInteger(event.pointer_id)) { failure(r, 'invalid_input_journal'); return; }
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
  const manifest = { schema: 'sphere-browser-teaching-v1', id: r.id, config: r.config,
    started_at_ms: r.at, finalized_at_ms: stamp(), frames: r.frames, events: r.events, files,
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
