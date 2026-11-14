import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '@/lib/api';
import { AndroidProfilePanel, parseAndroidProfile } from '@/src/features/devices/AndroidProfilePanel';

let token = 'fixture-token';
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: token }) }));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
jest.mock('@/src/features/devices/DeviceOperationsPanels', () => ({ utcTime: (value: unknown) => String(value) }));
const replies = ['[ro.product.model]: [Fixture]\n[vendor.secret]: [not-imported]', 'processor: 0\nmodel name: guest',
  'MemTotal: 2048000 kB\nMemAvailable: 1024000 kB', 'Physical size: 540x960', 'Physical density: 240',
  '2: eth0 inet 10.0.2.15/24 brd 10.0.2.255 scope global eth0', '100.12 160.24'];
beforeEach(() => { jest.clearAllMocks(); token = 'fixture-token'; });
it('excludes arbitrary vendor properties and keeps guest-reported identity', () => {
  expect(parseAndroidProfile('properties', replies[0])).toEqual([{ key: 'ro.product.model', value: 'Fixture' }]);
});
it.each(['cpu', 'memory', 'display', 'density', 'network', 'uptime'] as const)('does not turn a command error into successful %s metrics', id => {
  expect(() => parseAndroidProfile(id, 'su: permission denied')).toThrow();
});
it.each(['', 'x'.repeat(128 * 1024 + 1), 'bad\0value', 'x'.repeat(4097)])('bounds malformed input', output => {
  expect(() => parseAndroidProfile('properties', output)).toThrow();
});
it('performs only explicit serial fixed reads and displays all seven timestamped sections', async () => {
  for (const output of replies) jest.mocked(api.post).mockResolvedValueOnce({ data: { output } });
  render(<AndroidProfilePanel deviceId="remote" enabled />);
  expect(api.post).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Прочитать Android' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Получено 7 из 7'));
  expect(jest.mocked(api.post).mock.calls.map(call => call[1])).toEqual([
    'getprop', 'cat /proc/cpuinfo', 'cat /proc/meminfo', 'wm size', 'wm density', 'ip -o addr show', 'cat /proc/uptime',
  ].map(command => ({ command })));
  expect(screen.getByText('Fixture')).toBeInTheDocument();
  expect(screen.queryByText('not-imported')).not.toBeInTheDocument();
  expect(screen.getByText('10.0.2.15/24')).toBeInTheDocument();
});
it('stops at an unconfirmed read and never retries it or subsequent sources', async () => {
  jest.mocked(api.post).mockResolvedValueOnce({ data: { output: replies[0] } }).mockResolvedValueOnce({ data: { error: 'native denied' } });
  render(<AndroidProfilePanel deviceId="remote" enabled />);
  fireEvent.click(screen.getByRole('button', { name: 'Прочитать Android' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('native denied');
  expect(screen.getByRole('status')).toHaveTextContent('Получено 1 из 7');
  expect(api.post).toHaveBeenCalledTimes(2);
});
it('aborts on auth/target change and ignores an old result without sending more commands', async () => {
  let finish!: (value: unknown) => void;
  jest.mocked(api.post).mockImplementationOnce(() => new Promise(r => { finish = r; }) as never);
  const view = render(<AndroidProfilePanel deviceId="remote" enabled />);
  fireEvent.click(screen.getByRole('button', { name: 'Прочитать Android' }));
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal as AbortSignal;
  token = 'other'; view.rerender(<AndroidProfilePanel deviceId="other" enabled />);
  expect(signal.aborted).toBe(true);
  await act(async () => { finish({ data: { output: replies[0] } }); });
  expect(api.post).toHaveBeenCalledTimes(1); expect(screen.queryByText('Fixture')).not.toBeInTheDocument();
});
it('stops the next read when freshness is lost without a React effect delay', async () => {
  let finish!: (value: unknown) => void;
  jest.mocked(api.post).mockImplementationOnce(() => new Promise(r => { finish = r; }) as never);
  const view = render(<AndroidProfilePanel deviceId="remote" enabled />);
  fireEvent.click(screen.getByRole('button', { name: 'Прочитать Android' }));
  view.rerender(<AndroidProfilePanel deviceId="remote" enabled={false} />);
  await act(async () => { finish({ data: { output: replies[0] } }); });
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('status')).toHaveTextContent('Получено 1 из 7');
});
it('bounds the whole profile read to one minute without replaying timed-out commands', async () => {
  jest.useFakeTimers();
  try {
    jest.mocked(api.post).mockImplementationOnce((_url, _body, config) => new Promise((_resolve, reject) => {
      config?.signal?.addEventListener?.('abort', () => reject(new Error('profile deadline')), { once: true });
    }) as never);
    render(<AndroidProfilePanel deviceId="remote" enabled />);
    fireEvent.click(screen.getByRole('button', { name: 'Прочитать Android' }));
    await act(async () => { jest.advanceTimersByTime(60_000); });
    expect(screen.getByRole('alert')).toHaveTextContent('profile deadline');
    expect(api.post).toHaveBeenCalledTimes(1);
  } finally { jest.useRealTimers(); }
});
