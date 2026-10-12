import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AgentDownloadPanel } from '@/src/features/updates/AgentDownloadPanel';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const response = () => ({ data: new Blob(['apk']), headers: {
  'content-type': 'application/vnd.android.package-archive',
  'content-disposition': 'attachment; filename="SphereAgent-1.2.61-dev-android-canary-dev.apk"',
} });
let save: jest.SpyInstance;
beforeEach(() => {
  jest.clearAllMocks();
  URL.createObjectURL = jest.fn(() => 'blob:owned-apk');
  URL.revokeObjectURL = jest.fn();
  save = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
});
afterEach(() => save.mockRestore());

it('downloads the request-time latest APK and saves the server filename', async () => {
  jest.mocked(api.get).mockResolvedValue(response() as never);
  const view = render(<AgentDownloadPanel releases={[]} available />);
  fireEvent.click(screen.getByRole('button', { name: 'Скачать последний APK' }));
  await screen.findByText('APK передан браузеру для сохранения.');
  expect(api.get).toHaveBeenCalledWith('/updates/downloads/latest?platform=android-canary&flavor=dev', expect.objectContaining({
    signal: expect.any(AbortSignal), responseType: 'blob', timeout: 120_000,
  }));
  expect(save).toHaveBeenCalledTimes(1);
  const anchor = save.mock.instances[0] as HTMLAnchorElement;
  expect(anchor.download).toBe('SphereAgent-1.2.61-dev-android-canary-dev.apk');
  view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:owned-apk');
});

it('preserves platform and flavor selection rather than choosing a globally higher version', async () => {
  jest.mocked(api.get).mockResolvedValue(response() as never);
  render(<AgentDownloadPanel releases={[]} available />);
  fireEvent.change(screen.getByLabelText('Канал приложения'), { target: { value: 'android/enterprise' } });
  fireEvent.click(screen.getByRole('button', { name: 'Скачать последний APK' }));
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/updates/downloads/latest?platform=android&flavor=enterprise', expect.any(Object)));
});

it('aborts an account-owned download on unmount and ignores its late response', async () => {
  let finish!: (value: ReturnType<typeof response>) => void;
  jest.mocked(api.get).mockReturnValue(new Promise(resolve => { finish = resolve; }) as never);
  const view = render(<AgentDownloadPanel releases={[]} available />);
  fireEvent.click(screen.getByRole('button', { name: 'Скачать последний APK' }));
  const signal = jest.mocked(api.get).mock.calls[0][1]?.signal;
  view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => finish(response()));
  expect(save).not.toHaveBeenCalled();
});

it('supports cancellation and does not start duplicate downloads', async () => {
  let finish!: (value: ReturnType<typeof response>) => void;
  jest.mocked(api.get).mockReturnValue(new Promise(resolve => { finish = resolve; }) as never);
  render(<AgentDownloadPanel releases={[]} available />);
  const button = screen.getByRole('button', { name: 'Скачать последний APK' });
  fireEvent.click(button); fireEvent.click(button);
  expect(api.get).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Отменить' }));
  expect(jest.mocked(api.get).mock.calls[0][1]?.signal?.aborted).toBe(true);
  await act(async () => finish(response()));
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Скачать последний APK' })).toBeEnabled();
});

it('rejects an ingress error page rather than saving HTML as an APK', async () => {
  jest.mocked(api.get).mockResolvedValue({ data: new Blob(['<html>error</html>']), headers: { 'content-type': 'text/html' } } as never);
  render(<AgentDownloadPanel releases={[]} available />);
  fireEvent.click(screen.getByRole('button', { name: 'Скачать последний APK' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось скачать APK');
  expect(save).not.toHaveBeenCalled();
});

it('links only to the official LDPlayer page in a separate protected tab', () => {
  render(<AgentDownloadPanel releases={[]} available={false} />);
  const link = screen.getByRole('link', { name: /Скачать LDPlayer/ });
  expect(link).toHaveAttribute('href', 'https://www.ldplayer.net/');
  expect(link).toHaveAttribute('target', '_blank');
  expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  expect(screen.getByRole('button', { name: 'Скачать последний APK' })).toBeDisabled();
});
