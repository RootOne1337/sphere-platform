import { act, fireEvent, render, screen } from '@testing-library/react';
import { TextDecoder, TextEncoder } from 'util';
import { api } from '@/lib/api';
import { NativeScreenshotPanel, nativeCaptureError, verifyNativeScreenshot } from '@/src/features/devices/NativeScreenshotPanel';

let token = 'fixture-token';
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: token }) }));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
jest.mock('@/src/features/devices/DeviceOperationsPanels', () => ({ utcTime: (value: unknown) => String(value) }));
const hash = '0'.repeat(64);
const headers = {
  'content-type': 'image/png', 'x-screenshot-device-id': 'remote', 'x-screenshot-id': 'a'.repeat(32),
  'x-screenshot-sha256': hash, 'x-screenshot-android-sha256': hash, 'x-screenshot-width': '2', 'x-screenshot-height': '1',
  'x-screenshot-requested-at': '2026-10-04T00:00:00Z', 'x-screenshot-completed-at': '2026-10-04T00:00:01Z',
  'x-screenshot-cleanup-confirmed': 'true',
};
function png() {
  const buffer = new ArrayBuffer(80), bytes = new Uint8Array(buffer);
  bytes.set([137, 80, 78, 71, 13, 10, 26, 10]);
  const view = new DataView(buffer); view.setUint32(16, 2); view.setUint32(20, 1);
  return buffer;
}
beforeEach(() => {
  jest.clearAllMocks(); token = 'fixture-token';
  Object.defineProperty(global, 'crypto', { configurable: true, value: { subtle: { digest: jest.fn().mockResolvedValue(new ArrayBuffer(32)) } } });
  Object.defineProperty(global, 'TextDecoder', { configurable: true, value: TextDecoder });
  URL.createObjectURL = jest.fn().mockReturnValue('blob:verified-fixture');
  URL.revokeObjectURL = jest.fn();
  jest.mocked(api.post).mockResolvedValue({ data: png(), headers });
});
it('requests no capture on mount and downloads the verified original bytes without video', async () => {
  const view = render(<NativeScreenshotPanel deviceId="remote" enabled />);
  expect(api.post).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Получить снимок' }));
  expect(api.post).toHaveBeenCalledWith('/devices/remote/screenshot/native', {}, expect.objectContaining({ timeout: 100_000, responseType: 'arraybuffer' }));
  const link = await screen.findByRole('link', { name: 'Скачать исходный PNG' });
  expect(link).toHaveAttribute('href', 'blob:verified-fixture');
  expect(link).toHaveAttribute('download', `sphere-remote-${'a'.repeat(32)}.png`);
  expect(screen.getByText('2 × 1 · 80 байт')).toBeInTheDocument();
  expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
  view.unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:verified-fixture');
});
it.each([
  { 'x-screenshot-device-id': 'other' }, { 'content-type': 'image/jpeg' },
  { 'x-screenshot-sha256': 'f'.repeat(64) }, { 'x-screenshot-width': '3' },
  { 'x-screenshot-android-sha256': undefined }, { 'x-screenshot-android-sha256': 'f'.repeat(64) },
  { 'x-screenshot-completed-at': 'invalid' }, { 'x-screenshot-cleanup-confirmed': undefined },
])('rejects wrong target, changed bytes and incomplete evidence without offering download', async mismatch => {
  jest.mocked(api.post).mockResolvedValueOnce({ data: png(), headers: { ...headers, ...mismatch } });
  render(<NativeScreenshotPanel deviceId="remote" enabled />);
  fireEvent.click(screen.getByRole('button', { name: 'Получить снимок' }));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  expect(URL.createObjectURL).not.toHaveBeenCalled(); expect(api.post).toHaveBeenCalledTimes(1);
});
it('shows unconfirmed cleanup separately from a valid file', async () => {
  jest.mocked(api.post).mockResolvedValueOnce({ data: png(), headers: { ...headers, 'x-screenshot-cleanup-confirmed': 'false' } });
  render(<NativeScreenshotPanel deviceId="remote" enabled />);
  fireEvent.click(screen.getByRole('button', { name: 'Получить снимок' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('удаление временных файлов');
  expect(screen.getByRole('link')).toBeInTheDocument();
});
it('synchronously locks duplicate capture, aborts on target/auth change and ignores late pixels', async () => {
  let finish!: (value: unknown) => void;
  jest.mocked(api.post).mockImplementationOnce(() => new Promise(r => { finish = r; }) as never);
  const view = render(<NativeScreenshotPanel deviceId="remote" enabled />);
  const button = screen.getByRole('button', { name: 'Получить снимок' });
  act(() => { fireEvent.click(button); fireEvent.click(button); });
  expect(api.post).toHaveBeenCalledTimes(1);
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal as AbortSignal;
  token = 'new-session'; view.rerender(<NativeScreenshotPanel deviceId="other" enabled />);
  expect(signal.aborted).toBe(true);
  await act(async () => { finish({ data: png(), headers }); });
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});
it('switches to native pixel size without recapture or replacing the verified download', async () => {
  render(<NativeScreenshotPanel deviceId="remote" enabled />);
  fireEvent.click(screen.getByRole('button', { name: 'Получить снимок' }));
  const link = await screen.findByRole('link', { name: 'Скачать исходный PNG' });
  const image = screen.getByRole('img', { name: 'Исходный снимок выбранного Android-устройства' });
  fireEvent.click(screen.getByRole('button', { name: '100% · 1:1' }));
  expect(screen.getByRole('button', { name: '100% · 1:1' })).toHaveAttribute('aria-pressed', 'true');
  expect(image).toHaveStyle({ width: '2px', height: '1px' });
  expect(image).toHaveClass('max-w-none');
  expect(link).toHaveAttribute('href', 'blob:verified-fixture');
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Вписать в панель' }));
  expect(image).toHaveStyle({ width: '', height: '' });
  expect(image).toHaveClass('max-w-full');
});
it('drops native preview mode and its old image when the target changes', async () => {
  const view = render(<NativeScreenshotPanel deviceId="remote" enabled />);
  fireEvent.click(screen.getByRole('button', { name: 'Получить снимок' }));
  await screen.findByRole('link', { name: 'Скачать исходный PNG' });
  fireEvent.click(screen.getByRole('button', { name: '100% · 1:1' }));
  view.rerender(<NativeScreenshotPanel deviceId="other" enabled />);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:verified-fixture');
  jest.mocked(api.post).mockResolvedValueOnce({ data: png(), headers: { ...headers, 'x-screenshot-device-id': 'other' } });
  fireEvent.click(screen.getByRole('button', { name: 'Получить снимок' }));
  await screen.findByRole('link', { name: 'Скачать исходный PNG' });
  expect(screen.getByRole('button', { name: 'Вписать в панель' })).toHaveAttribute('aria-pressed', 'true');
});
it('cannot capture when device freshness/permission disables the panel', () => {
  render(<NativeScreenshotPanel deviceId="remote" enabled={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'Получить снимок' }));
  expect(api.post).not.toHaveBeenCalled();
});
it('aborts capture and discards a late file when device freshness is lost', async () => {
  let finish!: (value: unknown) => void;
  jest.mocked(api.post).mockImplementationOnce(() => new Promise(r => { finish = r; }) as never);
  const view = render(<NativeScreenshotPanel deviceId="remote" enabled />);
  fireEvent.click(screen.getByRole('button', { name: 'Получить снимок' }));
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal as AbortSignal;
  view.rerender(<NativeScreenshotPanel deviceId="remote" enabled={false} />);
  expect(signal.aborted).toBe(true);
  await act(async () => { finish({ data: png(), headers }); });
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});
it('rejects empty, oversized and non-PNG responses before creating a browser file', async () => {
  for (const value of [new ArrayBuffer(0), new ArrayBuffer(5 * 1024 * 1024 + 1), new ArrayBuffer(80)]) {
    await expect(verifyNativeScreenshot(value, headers, 'remote')).rejects.toThrow();
  }
});
it('shows binary-endpoint error detail, failed phase and correlation ID without offering retry/download', async () => {
  const data = new TextEncoder().encode(JSON.stringify({ detail: 'Command timeout after 8.0s' })).buffer;
  jest.mocked(api.post).mockRejectedValueOnce({ response: { data, headers: {
    'x-screenshot-id': 'a'.repeat(32), 'x-screenshot-failed-phase': 'chunk_read',
    'x-screenshot-elapsed-ms': '8001', 'x-screenshot-cleanup-confirmed': 'false',
  } } });
  render(<NativeScreenshotPanel deviceId="remote" enabled />);
  fireEvent.click(screen.getByRole('button', { name: 'Получить снимок' }));
  const error = await screen.findByRole('alert');
  expect(error).toHaveTextContent('Command timeout after 8.0s');
  expect(error).toHaveTextContent('передача блока');
  expect(error).toHaveTextContent('a'.repeat(32));
  expect(error).toHaveTextContent('Удаление временных файлов не подтверждено');
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});
it.each([
  { data: new ArrayBuffer(16 * 1024 + 1), headers: {} },
  { data: new ArrayBuffer(10), headers: {} },
  { data: { detail: 'x'.repeat(513) }, headers: {} },
])('keeps malformed or oversized binary errors bounded', response => {
  expect(nativeCaptureError({ response })).toBe('Исходный снимок не получен.');
});
it('does not expose malformed IDs or arbitrary phase strings from headers', () => {
  const text = nativeCaptureError({ response: { data: { detail: 'Unavailable' }, headers: {
    'x-screenshot-id': '../private-token', 'x-screenshot-failed-phase': '<script>private</script>',
  } } });
  expect(text).toBe('Unavailable');
});
