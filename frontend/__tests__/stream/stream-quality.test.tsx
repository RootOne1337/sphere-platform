import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '@/lib/api';
import { StreamQualityControl } from '@/src/features/stream/StreamQualityControl';
import { parseStreamQuality, qualityDraft } from '@/src/features/stream/streamQuality';

let version = 1;
jest.mock('@/lib/store', () => ({ useAuthStore: (select: (s: unknown) => unknown) => select({ sessionVersion: version }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
const snapshot = () => ({ supported: true, protocol: 1, settings: { profile: 'auto', max_fps: null, max_bitrate_bps: null },
  active: { width: 960, height: 540, source_fps: 60, codec_max_fps: 60, target_fps: 60,
    max_bitrate_bps: 12_441_600, target_bitrate_bps: 2_000_000, adaptation: 'webrtc' } });
beforeEach(() => { jest.resetAllMocks(); version = 1; jest.mocked(api.get).mockResolvedValue({ data: snapshot() }); });
async function open(readOnly = false) {
  const view = render(<StreamQualityControl deviceId="one" readOnly={readOnly} />);
  fireEvent.click(screen.getByRole('button', { name: 'Качество видеопотока' }));
  await screen.findByLabelText('Профиль'); return view;
}
test('mounting a viewer sends no quality commands; opening reads one current APK snapshot', async () => {
  render(<StreamQualityControl deviceId="one" readOnly={false} />);
  expect(api.get).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Качество видеопотока' }));
  expect(await screen.findByLabelText('Текущие параметры Android')).toHaveTextContent('960 × 540');
  expect(screen.getByLabelText('Лимит FPS')).toHaveValue(null);
  expect(screen.getByRole('button', { name: 'Применить' })).toBeDisabled();
});
test('one write waits for Android confirmation and does not change the capture connection', async () => {
  await open();
  let finish!: (v: unknown) => void;
  jest.mocked(api.post).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  fireEvent.change(screen.getByLabelText('Профиль'), { target: { value: 'detail' } });
  fireEvent.change(screen.getByLabelText('Лимит битрейта, Мбит/с'), { target: { value: '12' } });
  fireEvent.click(screen.getByRole('button', { name: 'Применить' }));
  expect(screen.queryByText(/Android сохранил/)).not.toBeInTheDocument();
  expect(api.post).toHaveBeenCalledWith('/streaming/one/quality', { profile: 'detail', max_fps: null, max_bitrate_bps: 12_000_000 }, expect.any(Object));
  await act(async () => finish({ data: { ...snapshot(), settings: { profile: 'detail', max_fps: null, max_bitrate_bps: 12_000_000 } } }));
  expect(screen.getByRole('status')).toHaveTextContent('Android сохранил');
  expect(api.post).toHaveBeenCalledTimes(1);
});
test('unknown completion is shown honestly without retrying a write', async () => {
  await open(); jest.mocked(api.post).mockRejectedValueOnce(new Error('timeout'));
  fireEvent.change(screen.getByLabelText('Профиль'), { target: { value: 'detail' } });
  fireEvent.click(screen.getByRole('button', { name: 'Применить' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Настройки могли примениться');
  expect(api.post).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Обновить' }));
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  expect(api.post).toHaveBeenCalledTimes(1);
});
test('read-only participant can inspect quality but cannot mutate the shared encoder', async () => {
  await open(true);
  expect(screen.getByLabelText('Профиль')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Применить' })).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});
test('device or account change discards a pending old-device response and dialog', async () => {
  let finish!: (v: unknown) => void;
  jest.mocked(api.get).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const view = render(<StreamQualityControl deviceId="one" readOnly={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'Качество видеопотока' }));
  const signal = jest.mocked(api.get).mock.calls[0][1]!.signal as AbortSignal;
  version++;
  view.rerender(<StreamQualityControl deviceId="two" readOnly={false} />);
  expect(signal.aborted).toBe(true);
  await act(async () => finish({ data: snapshot() }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
test('form bounds and native auto choice are validated before sending', () => {
  expect(qualityDraft('auto', '', '')).toEqual(snapshot().settings);
  expect(qualityDraft('detail', '60', '12.5')).toEqual({ profile: 'detail', max_fps: 60, max_bitrate_bps: 12_500_000 });
  for (const fps of ['0', '61', '1.5', 'NaN', 'Infinity']) expect(qualityDraft('auto', fps, '')).toBeNull();
  for (const rate of ['0.01', '32.1', 'NaN', 'Infinity']) expect(qualityDraft('auto', '', rate)).toBeNull();
});
test('invalid or incoherent APK snapshots are never presented as current applied quality', () => {
  expect(parseStreamQuality(snapshot())).not.toBeNull();
  expect(parseStreamQuality({ ...snapshot(), active: { ...snapshot().active, source_fps: 30 } })).toBeNull();
  expect(parseStreamQuality({ ...snapshot(), active: { ...snapshot().active, target_bitrate_bps: 32_000_000 } })).toBeNull();
  expect(parseStreamQuality({ ...snapshot(), supported: 'true' })).toBeNull();
  expect(parseStreamQuality({ ...snapshot(), settings: { profile: 'lossless', max_fps: null, max_bitrate_bps: null } })).toBeNull();
});
