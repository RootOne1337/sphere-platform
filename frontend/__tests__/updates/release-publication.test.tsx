import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '@/lib/api';
import { CreateReleaseDialog } from '@/src/features/updates/CreateReleaseDialog';
import { publicationFailure, validateReleaseDraft, verifyReleaseReceipt, type ReleaseDraft } from '@/src/features/updates/releasePublication';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
const draft: ReleaseDraft = { platform: 'android', flavor: 'enterprise', version_code: '10241', version_name: '1.2.41',
  download_url: '/api/v1/updates/artifacts/' + 'a'.repeat(64), sha256: 'a'.repeat(64), mandatory: false, changelog: '' };
const intent = validateReleaseDraft(draft).intent!;
const receipt = { ...intent, id: '11111111-1111-4111-8111-111111111111', created_at: '2026-10-03T03:00:00Z' };
const created = jest.fn();
beforeEach(() => jest.resetAllMocks());
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
async function open(available = true) {
  const view = render(<CreateReleaseDialog available={available} onCreated={created} />);
  fireEvent.click(screen.getByRole('button', { name: '+ New Release' }));
  if (available) await screen.findByRole('dialog');
  return view;
}
function fill() {
  const labels = { version_code: 'Номер версии (versionCode)', version_name: 'Имя версии из APK', download_url: 'HTTPS URL или managed-путь', sha256: 'SHA-256 APK' };
  for (const [key, label] of Object.entries(labels)) fireEvent.change(screen.getByLabelText(label), { target: { value: draft[key as keyof ReleaseDraft] } });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Подтверждаю совместимость APK и область публикации' }));
}

it.each(['', 'a'.repeat(63), 'A'.repeat(64)])('requires an exact lowercase checksum: %s', sha256 => {
  expect(validateReleaseDraft({ ...draft, sha256 }).errors.sha256).toBeTruthy();
});
it.each(['0', '-1', '1.2', '1e3', '2147483648'])('rejects invalid Android version %s', version_code => {
  expect(validateReleaseDraft({ ...draft, version_code }).errors.version_code).toBeTruthy();
});
it.each(['https://', 'http://server.test/a.apk', 'https://user:password@server.test/a.apk', 'https://server.test/a.apk#x', 'https://server.test/a apk', '/api/v1/updates/artifacts/' + 'b'.repeat(64)])('rejects an unsafe or mismatched URL: %s', download_url => {
  expect(validateReleaseDraft({ ...draft, download_url }).errors.download_url).toBeTruthy();
});
it('preserves signed HTTPS queries and accepts staged managed artifacts', () => {
  expect(validateReleaseDraft(draft).intent).toEqual(intent);
  const url = 'https://server.test/a.apk?signature=a%2Bb';
  expect(validateReleaseDraft({ ...draft, download_url: url }).intent?.download_url).toBe(url);
});
it.each([{ sha256: 'b'.repeat(64) }, { version_code: 10240 }, { platform: 'android-canary' }, { mandatory: true }, { id: '' }, { created_at: 'yesterday' }])('rejects a mismatched publication receipt: %p', patch => {
  expect(() => verifyReleaseReceipt({ ...receipt, ...patch }, intent)).toThrow();
});
it('classifies rejection separately from an uncertain commit', () => {
  expect(publicationFailure({ response: { status: 422 } }).unknown).toBe(false);
  expect(publicationFailure({ response: { status: 403 } }).unknown).toBe(false);
  expect(publicationFailure({ response: { status: 409 } }).unknown).toBe(true);
  expect(publicationFailure(new Error('timeout')).unknown).toBe(true);
});
it('cannot open a publication form without a current catalog', async () => {
  await open(false);
  expect(screen.getByRole('button', { name: '+ New Release' })).toBeDisabled();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});
it('requires impact consent and shows field errors without sending invalid data', async () => {
  await open();
  expect(screen.getByRole('button', { name: 'Опубликовать релиз' })).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Подтверждаю совместимость APK и область публикации' }));
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать релиз' }));
  expect(screen.getByLabelText('Номер версии (versionCode)')).toHaveAttribute('aria-invalid', 'true');
  expect(screen.getByLabelText('SHA-256 APK')).toHaveAttribute('aria-invalid', 'true');
  expect(api.post).not.toHaveBeenCalled();
});
it('sends one exact managed release and waits for an exact receipt', async () => {
  const pending = deferred<unknown>();
  jest.mocked(api.post).mockReturnValue(pending.promise as never);
  await open(); fill();
  const publish = screen.getByRole('button', { name: 'Опубликовать релиз' });
  fireEvent.click(publish); fireEvent.click(publish);
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith('/updates/', intent, { signal: expect.any(AbortSignal) });
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  await act(async () => { pending.resolve({ status: 201, data: receipt }); });
  expect(await screen.findByRole('status')).toHaveTextContent('Установка на устройства ещё не подтверждена');
  expect(created).toHaveBeenCalledTimes(1);
});
it('shows a rejected artifact in the dialog without alert or auto-retry', async () => {
  jest.mocked(api.post).mockRejectedValue({ response: { status: 422 } });
  await open(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Опубликовать релиз' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Сервер отклонил');
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('reconciles a lost publication reply using GET and never repeats POST', async () => {
  jest.mocked(api.post).mockRejectedValue(new Error('timeout'));
  jest.mocked(api.get).mockResolvedValue({ data: { releases: [receipt], total: 1 } } as never);
  await open(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Опубликовать релиз' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Результат публикации неизвестен');
  expect(screen.getByRole('button', { name: 'Опубликовать релиз' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Сверить результат с каталогом' }));
  expect(await screen.findByRole('status')).toHaveTextContent('подтверждено повторным чтением');
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(created).toHaveBeenCalledTimes(1);
});
it('does not treat a conflict with another artifact as saved', async () => {
  jest.mocked(api.post).mockRejectedValue({ response: { status: 409 } });
  jest.mocked(api.get).mockResolvedValue({ data: { releases: [{ ...receipt, sha256: 'b'.repeat(64) }], total: 1 } } as never);
  await open(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Опубликовать релиз' }));
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Сверить результат с каталогом' }));
  expect(await screen.findByText(/Точное сохранение не подтверждено/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Опубликовать релиз' })).toBeDisabled();
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(created).not.toHaveBeenCalled();
});
it('a malformed success response remains uncertain', async () => {
  jest.mocked(api.post).mockResolvedValue({ status: 201, data: { ...receipt, mandatory: true } } as never);
  await open(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Опубликовать релиз' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Результат публикации неизвестен');
  expect(created).not.toHaveBeenCalled();
});
it('aborts an old actor request and ignores a late publication reply after unmount', async () => {
  const pending = deferred<unknown>();
  jest.mocked(api.post).mockReturnValue(pending.promise as never);
  const view = await open(); fill(); fireEvent.click(screen.getByRole('button', { name: 'Опубликовать релиз' }));
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal;
  view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => { pending.resolve({ status: 201, data: receipt }); });
  expect(created).not.toHaveBeenCalled();
});
