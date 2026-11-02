/** @jest-environment node */
import {projectTeachingCatalogStatus, readTeachingCatalogStatus, readTeachingCatalogStatuses} from '@/src/features/stream/teachingCatalogStatus';
import {readReconstructionLink, listReconstructionLinks} from '@/src/features/stream/reconstructionLink';
import {reconstructionRequest, ReconstructionResponseError, type ReconstructionState} from '@/src/features/stream/reconstructionClient';
import type {TeachingLibraryRecord} from '@/src/features/stream/teachingLibrary';
import {teachingCatalogPresentation, teachingCatalogReason} from '@/src/features/stream/teachingCatalog';

jest.mock('@/src/features/stream/reconstructionLink', () => ({readReconstructionLink: jest.fn(), listReconstructionLinks: jest.fn()}));
jest.mock('@/src/features/stream/reconstructionClient', () => ({...jest.requireActual('@/src/features/stream/reconstructionClient'), reconstructionRequest: jest.fn()}));
const sha = 'a'.repeat(64), job = {id: 'b'.repeat(32), key: 'c'.repeat(64)}, checkedAt = 1793610000000;
const record = (id = 'd'.repeat(32)): TeachingLibraryRecord => ({id, title: 'Источник', createdAt: checkedAt - 1000, complete: true, frames: 857,
  manifestSha: sha, sourceState: 'saved', hudHidden: false, prepareAfterRecording: true, folder: {} as FileSystemDirectoryHandle});
const response = (status: unknown) => ({json: async () => status}) as Response;
const state = (value: Partial<ReconstructionState> = {}): ReconstructionState => ({phase: 'sparse_complete', source_manifest_sha256: sha, ...value});
beforeEach(() => {jest.clearAllMocks(); jest.mocked(readReconstructionLink).mockResolvedValue(job); jest.mocked(listReconstructionLinks).mockResolvedValue([]);});

test('source-bound status separates calculated scene from navigation readiness', () => {
  const projected = projectTeachingCatalogStatus(state(), sha, job.id, checkedAt);
  expect(projected).toMatchObject({preparation: {phase: 'ready', jobId: job.id, updatedAt: checkedAt}, navigation: {phase: 'not_prepared'}, statusCheckedAt: checkedAt});
  const map = projectTeachingCatalogStatus(state({navigation: {phase: 'ready'}}), sha, job.id, checkedAt);
  expect(map.navigation?.phase).toBe('ready');
  expect(teachingCatalogPresentation({...record(), ...projected}, {nowMs: checkedAt}).mapForReview).toBe(false);
  expect(teachingCatalogPresentation({...record(), ...map}, {nowMs: checkedAt}).mapForReview).toBe(true);
});
test.each(['f'.repeat(64), null, undefined])('mismatched/missing source SHA %s cannot inherit ready navigation', source_manifest_sha256 => {
  const projected = projectTeachingCatalogStatus(state({source_manifest_sha256, navigation: {phase: 'ready'}}), sha, job.id, checkedAt);
  expect(projected.preparation).toMatchObject({phase: 'unavailable', reason: 'catalog_source_unconfirmed'});
  expect(projected.navigation).toEqual({phase: 'unavailable', error: 'catalog_source_unconfirmed'});
});
test('pending initial upload may lack a source SHA, but never inherits an unbound navigation map', () => {
  const projected = projectTeachingCatalogStatus(state({phase: 'uploading', source_manifest_sha256: null, navigation: {phase: 'ready'}}), sha, job.id, checkedAt);
  expect(projected.preparation?.phase).toBe('uploading'); expect(projected.navigation?.phase).toBe('not_prepared');
});
test.each(['pending_auto_prepare', 'preparing', 'features'])('navigation phase %s keeps calculation in progress', phase => {
  expect(projectTeachingCatalogStatus(state({navigation: {phase}}), sha, job.id, checkedAt).preparation?.phase).toBe('processing');
});
test.each(['temporal_tracking','temporal_verification','temporal_cameras'])('source-bound temporal phase %s remains a valid processing status without navigation admission',async phase=>{
  const actual=state({phase,navigation:{phase:'not_prepared'}});
  const projected=projectTeachingCatalogStatus(actual,sha,job.id,checkedAt);
  expect(projected.preparation).toMatchObject({phase:'processing',jobId:job.id});
  expect(projected.navigation?.phase).toBe('not_prepared');
  jest.mocked(reconstructionRequest).mockResolvedValue(response(actual));
  const read=await readTeachingCatalogStatus(record());
  expect(read.preparation?.phase).toBe('processing');expect(read.preparation?.reason).not.toBe('catalog_status_invalid');
  expect(teachingCatalogPresentation({...record(),...read},{nowMs:Date.now()}).mapForReview).toBe(false);
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);
});
test.each(['failed', 'quality_rejected', 'cancelled'] as const)('terminal phase %s is preserved without creating a retry', phase => {
  const projected = projectTeachingCatalogStatus(state({phase, error: 'resource_guard'}), sha, job.id, checkedAt);
  expect(projected.preparation?.phase).toBe(phase === 'cancelled' ? 'cancelled' : 'failed');
  expect(projected.preparation?.reason).toBe('resource_guard'); expect(reconstructionRequest).not.toHaveBeenCalled();
});
test('without a saved capability, metadata read has no network side effects', async () => {
  jest.mocked(readReconstructionLink).mockResolvedValue(null);
  expect(await readTeachingCatalogStatus(record())).toEqual({}); expect(reconstructionRequest).not.toHaveBeenCalled();
});
test('one archived capability is read with GET when the current pointer is missing, without restoring or starting a job', async () => {
  const archived = {id: 'e'.repeat(32), key: 'f'.repeat(64)}, source = record();
  jest.mocked(readReconstructionLink).mockResolvedValue(null);
  jest.mocked(listReconstructionLinks).mockResolvedValue([archived]);
  jest.mocked(reconstructionRequest).mockResolvedValue(response(state({navigation: {phase: 'ready'}})));
  const projected = await readTeachingCatalogStatus(source);
  expect(listReconstructionLinks).toHaveBeenCalledWith(source.folder, source.id);
  expect(projected.preparation).toMatchObject({phase: 'ready', jobId: archived.id});
  expect(projected.navigation?.phase).toBe('ready');
  expect(reconstructionRequest).toHaveBeenCalledTimes(1);
  expect(reconstructionRequest).toHaveBeenCalledWith(`/jobs/${archived.id}`, archived, {signal: undefined});
});
test('multiple archived attempts without a current pointer remain ambiguous and never pick or query a job', async () => {
  jest.mocked(readReconstructionLink).mockResolvedValue(null);
  jest.mocked(listReconstructionLinks).mockResolvedValue([job, {id: 'e'.repeat(32), key: 'f'.repeat(64)}]);
  const projected = await readTeachingCatalogStatus(record());
  expect(projected.preparation).toMatchObject({phase: 'unavailable', reason: 'reconstruction_attempt_selection_required'});
  expect(projected.preparation?.jobId).toBeUndefined();
  expect(projected.navigation).toBeUndefined();
  expect(reconstructionRequest).not.toHaveBeenCalled();
});
test('without a verified manifest hash, a saved job capability is not enough to request/read a map', async () => {
  const projected = await readTeachingCatalogStatus({...record(), manifestSha: null});
  expect(projected.preparation).toMatchObject({phase: 'unavailable', reason: 'catalog_source_unconfirmed'});
  expect(reconstructionRequest).not.toHaveBeenCalled();
});
test.each([
  [new ReconstructionResponseError(403, 'job_access_denied'), 'catalog_access_denied', 'Нет доступа к заданию'],
  [new ReconstructionResponseError(404, 'job_not_found'), 'catalog_job_missing', 'Задание не найдено'],
  [new TypeError('Failed to fetch'), 'catalog_status_unavailable', 'Статус недоступен'],
  [new SyntaxError('bad JSON'), 'catalog_status_invalid', 'Ответ не подтверждён'],
] as const)('typed read failure %s does not infer a stopped local handler', async (error, reason, label) => {
  jest.mocked(reconstructionRequest).mockRejectedValue(error);
  const projected = await readTeachingCatalogStatus(record());
  expect(projected.preparation).toMatchObject({phase: 'unavailable', reason}); expect(projected.navigation?.error).toBe(reason);
  const view = teachingCatalogPresentation({...record(), ...projected}, {nowMs: Date.now()});
  expect(view.reconstruction.label).toBe(label);
  expect(teachingCatalogReason(reason)).not.toMatch(/запустите|должен быть запущен|обработчик недоступен/i);
});
test('malformed parsed status retains the invalid-response reason rather than becoming a network failure', async () => {
  jest.mocked(reconstructionRequest).mockResolvedValue(response({source_manifest_sha256: sha, navigation: {phase: 'ready'}}));
  const projected = await readTeachingCatalogStatus(record());
  expect(projected.preparation?.reason).toBe('catalog_status_invalid');
  expect(projected.navigation?.phase).toBe('unavailable');
});
test.each(['', 'not_a_real_job_phase'])('unrecognized phase %s is not advertised as processing', async phase => {
  jest.mocked(reconstructionRequest).mockResolvedValue(response(state({phase, navigation: {phase: 'ready'}})));
  const projected = await readTeachingCatalogStatus(record());
  expect(projected.preparation).toMatchObject({phase: 'unavailable', reason: 'catalog_status_invalid'});
  expect(projected.navigation?.phase).toBe('unavailable');
});
test('an unstructured server message is not copied into catalog captions or readiness', async () => {
  jest.mocked(reconstructionRequest).mockRejectedValue(new ReconstructionResponseError(500, '{"private":"not a status code"}'));
  const projected = await readTeachingCatalogStatus(record());
  expect(projected.preparation?.reason).toBe('catalog_status_unavailable');
  expect(teachingCatalogReason(projected.preparation?.reason)).not.toContain('private');
  expect(teachingCatalogPresentation({...record(), ...projected}, {nowMs: Date.now()}).mapForReview).toBe(false);
});
test('read timestamps come from successful observation rather than old persisted state', async () => {
  jest.spyOn(Date, 'now').mockReturnValue(checkedAt);
  try {
    jest.mocked(reconstructionRequest).mockResolvedValue(response({...state(), updated_at: 1}));
    const projected = await readTeachingCatalogStatus(record());
    expect(projected.statusCheckedAt).toBe(checkedAt); expect(projected.preparation?.updatedAt).toBe(checkedAt);
    expect(reconstructionRequest).toHaveBeenCalledWith(`/jobs/${job.id}`, job, {signal: undefined});
  } finally {jest.restoreAllMocks();}
});
test('the catalog uses at most two concurrent read-only GETs and covers every supplied recording', async () => {
  const records = Array.from({length: 7}, (_, i) => record(i.toString(16).padStart(32, '0')));
  let active = 0, maximum = 0;
  const release: (() => void)[] = [];
  jest.mocked(reconstructionRequest).mockImplementation(async () => {
    active++; maximum = Math.max(maximum, active);
    await new Promise<void>(resolve => release.push(resolve)); active--;
    return response(state());
  });
  const result = readTeachingCatalogStatuses(records);
  const settle = () => new Promise<void>(resolve => setImmediate(resolve));
  await settle(); expect(reconstructionRequest).toHaveBeenCalledTimes(2);
  for (let i = 0; i < records.length; i++) {expect(release.length).toBeGreaterThan(0); release.shift()!(); await settle();}
  expect(Object.keys(await result)).toEqual(expect.arrayContaining(records.map(row => row.id)));
  expect(maximum).toBe(2); expect(active).toBe(0);
  for (const [path, capability, init] of jest.mocked(reconstructionRequest).mock.calls) {
    expect(path).toBe(`/jobs/${job.id}`); expect(capability).toEqual(job); expect(init?.method ?? 'GET').toBe('GET');
  }
});
test('pre-aborted batch does not read capabilities or call an API', async () => {
  const abort = new AbortController(); abort.abort();
  await expect(readTeachingCatalogStatuses([record()], abort.signal)).rejects.toMatchObject({name: 'AbortError'});
  expect(readReconstructionLink).not.toHaveBeenCalled(); expect(reconstructionRequest).not.toHaveBeenCalled();
});
test('abort of an in-flight status read is propagated rather than shown as a handler failure', async () => {
  const abort = new AbortController();
  jest.mocked(reconstructionRequest).mockImplementation(async (_path, _job, init) => {
    expect(init?.signal).toBe(abort.signal); abort.abort(); throw new DOMException('Aborted', 'AbortError');
  });
  await expect(readTeachingCatalogStatus(record(), abort.signal)).rejects.toMatchObject({name: 'AbortError'});
  expect(reconstructionRequest).toHaveBeenCalledTimes(1);
});
