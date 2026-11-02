/** @jest-environment node */
import {webcrypto} from 'node:crypto';
import {readTeachingLibrary} from '@/src/features/stream/teachingLibrary';

const scope = 'b'.repeat(32), id = 'a'.repeat(32);
const encode = (value: unknown) => new TextEncoder().encode(typeof value === 'string' ? value : JSON.stringify(value));
const hash = async (value: ArrayBuffer) => Buffer.from(await webcrypto.subtle.digest('SHA-256', value)).toString('hex');
const file = (value: unknown, name: string) => new File([encode(value)], name);
const missing = () => new DOMException('Missing', 'NotFoundError');
type Row = {index: number; offset: number; bytes: number; relative_ticks_90k: number; sha256: string; key: boolean};
type Manifest = {
  schema: string; id: string; started_at_ms: number; complete: boolean; release_confirmed: boolean; frames: number; events: number;
  failure?: string; config: {title: string; device_id: string; profile: {mode: string; hudProfile: string}; hud_hidden_declared: boolean; prepare_after_recording: boolean};
  files: Record<string, {bytes: number; sha256?: string}>;
};
function directory(files: Map<string, File>) {
  const writes = jest.fn(() => {throw Error('Reader must never write');});
  const reads: string[] = [];
  const getFileHandle = jest.fn(async (name: string, options?: {create?: boolean}) => {
    reads.push(name); if (options?.create) writes();
    if (!files.has(name)) throw missing();
    return {getFile: async () => files.get(name)!, createWritable: writes};
  });
  return {folder: {getFileHandle, removeEntry: writes} as unknown as FileSystemDirectoryHandle, reads, writes, getFileHandle};
}
async function recording(options: {id?: string; at?: number; complete?: boolean; rows?: Row[]; events?: unknown[];
  indexFile?: File; journalFile?: File; change?: (manifest: Manifest) => void} = {}) {
  const clip = options.id ?? id, video = new File([new Uint8Array(16)], 'video.h264');
  const rows = options.rows ?? [0, 1].map(index => ({index, offset: index * 8, bytes: 8, relative_ticks_90k: index * 90000, sha256: 'c'.repeat(64), key: true}));
  const indexFile = options.indexFile ?? file(rows.map(row => JSON.stringify(row)).join('\n'), 'frames.jsonl');
  const events = options.events ?? [], journalFile = options.journalFile ?? file(events.map(event => JSON.stringify(event)).join('\n'), 'inputs.jsonl');
  const manifest: Manifest = {schema: 'sphere-browser-teaching-v2', id: clip, started_at_ms: options.at ?? 1793610000000,
    complete: options.complete ?? true, release_confirmed: true, frames: rows.length, events: events.length,
    config: {title: `Маршрут ${clip.slice(-4)}`, device_id: 'emulator-11', profile: {mode: 'vehicle_buttons', hudProfile: 'black_russia_scooter_v1'}, hud_hidden_declared: false, prepare_after_recording: true},
    files: {'video.h264': {bytes: video.size, sha256: 'd'.repeat(64)},
      'frames.jsonl': {bytes: indexFile.size, sha256: await hash(await indexFile.arrayBuffer())},
      'inputs.jsonl': {bytes: journalFile.size, sha256: await hash(await journalFile.arrayBuffer())}}};
  options.change?.(manifest);
  const manifestFile = file(manifest, 'manifest.json'), manifestSha = await hash(await manifestFile.arrayBuffer());
  const files = new Map<string, File>([['manifest.json', manifestFile], ['COMPLETE', file({manifest_sha256: manifestSha}, 'COMPLETE')],
    ['frames.jsonl', indexFile], ['inputs.jsonl', journalFile], ['video.h264', video]]);
  return {id: clip, files, manifest, manifestSha, ...directory(files)};
}
function library(records: {id: string; folder: FileSystemDirectoryHandle}[], extraEntries: [string, FileSystemHandle][] = []) {
  const folders = new Map(records.map(record => [record.id, record.folder]));
  const writes = jest.fn(() => {throw Error('Reader must never write');});
  const getDirectoryHandle = jest.fn(async (name: string, options?: {create?: boolean}) => {
    if (options?.create) writes(); if (!folders.has(name)) throw missing(); return folders.get(name)!;
  });
  const handle = {entries: async function* () {
    for (const extra of extraEntries) yield extra;
    for (const record of records) yield [record.id, {kind: 'directory', name: record.id}] as [string, FileSystemHandle];
  }, getDirectoryHandle, removeEntry: writes} as unknown as FileSystemDirectoryHandle;
  const rootGet = jest.fn(async (name: string, options?: {create?: boolean}) => {
    if (options?.create) writes(); if (name !== 'sphere-teaching-' + scope) throw missing(); return handle;
  });
  return {root: {getDirectoryHandle: rootGet, removeEntry: writes} as unknown as FileSystemDirectoryHandle, writes, rootGet, getDirectoryHandle};
}
beforeAll(() => {Object.defineProperty(globalThis, 'crypto', {configurable: true, value: webcrypto});});

test('seals source only after COMPLETE, index SHA/count/order and video size checks, without claiming full-video verification', async () => {
  const capture = await recording(), store = library([capture]);
  const videoRead = jest.spyOn(capture.files.get('video.h264')!, 'arrayBuffer').mockRejectedValue(Error('Full video must not be read by the catalog'));
  const result = await readTeachingLibrary(scope, {root: store.root});
  expect(result.truncated).toBe(false);
  expect(result.records[0]).toMatchObject({id, manifestSha: capture.manifestSha, sourceState: 'saved', complete: true, frames: 2, durationSeconds: 1,
    deviceId: 'emulator-11', controlMode: 'vehicle_buttons', hudProfile: 'black_russia_scooter_v1', hudHidden: false, prepareAfterRecording: true});
  expect(videoRead).not.toHaveBeenCalled();
  expect(capture.writes).not.toHaveBeenCalled(); expect(store.writes).not.toHaveBeenCalled();
  expect(capture.getFileHandle.mock.calls.every(call => call[1] === undefined)).toBe(true);
});
test.each([
  ['COMPLETE', 'teaching_library_complete_binding'], ['frames.jsonl', 'teaching_library_index_integrity'], ['inputs.jsonl', 'teaching_library_index_integrity'],
] as const)('changed %s cannot inherit a saved badge', async (filename, reason) => {
  const capture = await recording(); capture.files.set(filename, file(filename === 'COMPLETE' ? {manifest_sha256: 'e'.repeat(64)} : 'changed', filename));
  const result = await readTeachingLibrary(scope, {root: library([capture]).root});
  expect(result.records[0]).toMatchObject({id, complete: false, sourceState: 'unavailable', sourceFailure: reason});
});
test.each([
  ['release', (m: Manifest) => {m.release_confirmed = false;}, 'teaching_library_release_unconfirmed'],
  ['identity', (m: Manifest) => {m.id = 'f'.repeat(32);}, 'teaching_library_manifest_binding'],
  ['frame count', (m: Manifest) => {m.frames = 3;}, 'teaching_library_frame_index'],
  ['event count', (m: Manifest) => {m.events = 1;}, 'teaching_library_input_index'],
  ['video bytes', (m: Manifest) => {m.files['video.h264'].bytes = 17;}, 'teaching_library_video_size'],
] as const)('invalid %s remains visible with its exact reason', async (_name, change, reason) => {
  const capture = await recording({change}), result = await readTeachingLibrary(scope, {root: library([capture]).root});
  expect(result.records).toHaveLength(1);
  expect(result.records[0]).toMatchObject({sourceState: 'unavailable', sourceFailure: reason, complete: false});
});
test.each(['offset', 'time', 'hash', 'key'] as const)('a checksum-bound index still rejects invalid row %s', async mutation => {
  const rows = [0, 1].map(index => ({index, offset: index * 8, bytes: 8, relative_ticks_90k: index * 90000, sha256: 'c'.repeat(64), key: true}));
  if (mutation === 'offset') rows[1].offset = 9;
  if (mutation === 'time') rows[1].relative_ticks_90k = 0;
  if (mutation === 'hash') rows[1].sha256 = 'not-a-hash';
  if (mutation === 'key') (rows[1] as unknown as {key: unknown}).key = 'yes';
  const capture = await recording({rows}), result = await readTeachingLibrary(scope, {root: library([capture]).root});
  expect(result.records[0].sourceFailure).toBe('teaching_library_frame_index');
});
test('incomplete source and corrupt source both stay in the catalog rather than disappearing', async () => {
  const incomplete = await recording({complete: false, change: m => {m.failure = 'page_hidden';}});
  incomplete.files.delete('COMPLETE'); incomplete.files.delete('video.h264');
  const broken = {...directory(new Map([['manifest.json', file('{invalid json', 'manifest.json')]])), id: '1'.repeat(32)};
  const result = await readTeachingLibrary(scope, {root: library([incomplete, broken]).root});
  expect(result.records).toHaveLength(2);
  expect(result.records.find(row => row.id === id)).toMatchObject({sourceState: 'incomplete', sourceFailure: 'page_hidden'});
  expect(result.records.find(row => row.id === broken.id)).toMatchObject({sourceState: 'unavailable', sourceFailure: 'teaching_library_source_invalid'});
});
test('a renamed sidecar is accepted only for the same manifest; label damage cannot invalidate a saved video', async () => {
  const capture = await recording();
  const label = {schema: 'sphere-teaching-label-v1', id, manifest_sha256: capture.manifestSha, title: 'Скутер · спокойный маршрут', updated_at_ms: 1793610000000};
  capture.files.set('label.json', file(label, 'label.json'));
  expect((await readTeachingLibrary(scope, {root: library([capture]).root})).records[0]).toMatchObject({title: label.title, sourceState: 'saved'});
  capture.files.set('label.json', file({...label, manifest_sha256: 'e'.repeat(64)}, 'label.json'));
  const unchanged = await readTeachingLibrary(scope, {root: library([capture]).root});
  expect(unchanged.records[0]).toMatchObject({title: capture.manifest.config.title, sourceState: 'saved', manifestSha: capture.manifestSha});
  expect(capture.writes).not.toHaveBeenCalled();
});
test('a missing required source file and an oversized manifest are visible without writes', async () => {
  const absent = await recording(); absent.files.delete('frames.jsonl');
  const oversized = await recording({id: '2'.repeat(32)}); oversized.files.set('manifest.json', new File([' '.repeat(65537)], 'manifest.json'));
  const result = await readTeachingLibrary(scope, {root: library([absent, oversized]).root});
  expect(result.records.find(row => row.id === absent.id)?.sourceFailure).toBe('teaching_library_source_missing');
  expect(result.records.find(row => row.id === oversized.id)?.sourceFailure).toBe('teaching_library_file_quota');
  expect(absent.writes).not.toHaveBeenCalled(); expect(oversized.writes).not.toHaveBeenCalled();
});
test('more than 100 recordings include the newest item even when it is enumerated last', async () => {
  const records = await Promise.all(Array.from({length: 120}, (_, i) => recording({id: i.toString(16).padStart(32, '0'), at: 1000 + i, complete: false})));
  const result = await readTeachingLibrary(scope, {root: library(records).root});
  expect(result.records).toHaveLength(120); expect(result.truncated).toBe(false);
  expect(result.records[0].id).toBe((119).toString(16).padStart(32, '0'));
  expect(result.records.at(-1)!.id).toBe('0'.repeat(32));
});
test('directory and entry quotas stop at bounded limits and explicitly report truncation', async () => {
  const empty = directory(new Map());
  const records = Array.from({length: 513}, (_, i) => ({id: i.toString(16).padStart(32, '0'), folder: empty.folder}));
  const store = library(records), result = await readTeachingLibrary(scope, {root: store.root});
  expect(result.records).toHaveLength(512); expect(result.truncated).toBe(true); expect(store.getDirectoryHandle).toHaveBeenCalledTimes(512);
  const invalidEntries = Array.from({length: 4096}, (_, i) => [`ignored-${i}`, {kind: 'file'}] as [string, FileSystemHandle]);
  const capped = library([records[0]], invalidEntries), cappedResult = await readTeachingLibrary(scope, {root: capped.root});
  expect(cappedResult).toEqual({records: [], truncated: true}); expect(capped.getDirectoryHandle).not.toHaveBeenCalled();
});
test('aggregate 64MiB index budget leaves later records unverified before reading their payloads', async () => {
  const rowText = [0, 1].map(index => JSON.stringify({index, offset: index * 8, bytes: 8, relative_ticks_90k: index * 90000, sha256: 'c'.repeat(64), key: true})).join('\n');
  const indexFile = new File([rowText, ' '.repeat(16 * 1024 ** 2 - new TextEncoder().encode(rowText).length)], 'frames.jsonl');
  const journalFile = new File([' '.repeat(8 * 1024 ** 2)], 'inputs.jsonl');
  const records: Awaited<ReturnType<typeof recording>>[] = [];
  for (let i = 0; i < 3; i++) records.push(await recording({id: i.toString(16).padStart(32, '0'), indexFile, journalFile}));
  const indexRead = jest.spyOn(indexFile, 'arrayBuffer'), journalRead = jest.spyOn(journalFile, 'arrayBuffer');
  const result = await readTeachingLibrary(scope, {root: library(records).root});
  expect(result.records.filter(row => row.sourceState === 'saved')).toHaveLength(2);
  expect(result.records.find(row => row.id === records[2].id)).toMatchObject({sourceState: 'unverified', sourceFailure: 'teaching_library_scan_budget'});
  expect(result.truncated).toBe(true); expect(indexRead).toHaveBeenCalledTimes(2); expect(journalRead).toHaveBeenCalledTimes(2);
}, 10000);
test('invalid account and an already aborted read do not access storage', async () => {
  const store = library([]), abort = new AbortController(); abort.abort();
  await expect(readTeachingLibrary('../other-account', {root: store.root})).rejects.toThrow('teaching_library_scope');
  await expect(readTeachingLibrary(scope, {root: store.root, signal: abort.signal})).rejects.toMatchObject({name: 'AbortError'});
  expect(store.rootGet).not.toHaveBeenCalled(); expect(store.writes).not.toHaveBeenCalled();
});
test('abort during a manifest read rejects instead of returning a misleading partial success', async () => {
  const capture = await recording(), store = library([capture]), controller = new AbortController();
  const manifest = capture.files.get('manifest.json')!, original = manifest.arrayBuffer.bind(manifest);
  jest.spyOn(manifest, 'arrayBuffer').mockImplementation(async () => {controller.abort(); return original();});
  await expect(readTeachingLibrary(scope, {root: store.root, signal: controller.signal})).rejects.toMatchObject({name: 'AbortError'});
  expect(capture.reads).not.toContain('COMPLETE'); expect(capture.writes).not.toHaveBeenCalled(); expect(store.writes).not.toHaveBeenCalled();
});
test('an absent account library is empty and never gets created as a side effect', async () => {
  const getDirectoryHandle = jest.fn(async () => {throw missing();});
  expect(await readTeachingLibrary(scope, {root: {getDirectoryHandle} as unknown as FileSystemDirectoryHandle})).toEqual({records: [], truncated: false});
  expect(getDirectoryHandle).toHaveBeenCalledWith('sphere-teaching-' + scope);
});
