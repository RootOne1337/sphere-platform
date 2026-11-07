import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import UpdatesPage from '@/app/(dashboard)/updates/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
const id = '11111111-1111-4111-8111-111111111111';
const command = '22222222-2222-4222-8222-222222222222';
const digest = 'a'.repeat(64);
const release = { id: 'release-10240', platform: 'android-canary', flavor: 'dev', version_code: 10240,
  version_name: '1.2.40-dev', download_url: '/api/v1/updates/artifacts/' + digest,
  sha256: digest, mandatory: false, changelog: null, created_at: '2026-10-01T00:00:00Z' };
const now = () => new Date().toISOString();
const target = (patch: Record<string, unknown> = {}) => ({ id, name: 'PH025', status: 'online', is_active: true,
  agent_version: '1.2.22-dev', agent_version_code: 10222, last_heartbeat: now(), ...patch });
const grant = () => ({ command_id: command, sha256: digest, version_name: release.version_name, version_code: 10240,
  created_at: Math.floor(Date.now() / 1000), expires_at: Math.floor(Date.now() / 1000) + 600 });
let device: ReturnType<typeof target>;
let recovery: Record<string, unknown>;

beforeEach(() => {
  jest.resetAllMocks();
  useAuthStore.setState({ user: { id: 'operator', org_id: 'tenant', role: 'super_admin', email: 'operator@example.test' }, sessionVersion: 1 });
  device = target();
  recovery = { device_id: id, state: 'none', active: null, last_result: null, recent_results: [], observed_at: now() };
  jest.mocked(api.get).mockImplementation(async (url, options) => {
    if (String(url).startsWith('/updates/?')) return { data: { releases: [release], total: 1 } } as never;
    if (url === '/devices') { const page = (options?.params as { page?: number })?.page ?? 1;
      return { data: { items: [device], total: 51, page, per_page: 50, pages: 2 } } as never; }
    if (url === '/devices/' + id) return { data: device } as never;
    if (url === '/updates/recovery/' + id) return { data: recovery } as never;
    throw new Error('Unexpected GET');
  });
  jest.mocked(api.post).mockImplementation(async (url) => {
    if (url === '/updates/recovery') return { status: 201, data: { device_id: id, ...grant(), issued_before: 1, delivery_hint: 'wake_published' } } as never;
    if (url === '/updates/recovery/' + id + '/dispatch') return { status: 202, data: { device_id: id, command_id: command, delivery_hint: 'wake_published' } } as never;
    throw new Error('Unexpected POST');
  });
  jest.mocked(api.delete).mockResolvedValue({ status: 204 } as never);
});
afterEach(() => useAuthStore.setState({ user: null, sessionVersion: 0 }));
async function open() {
  render(<UpdatesPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Адресное OTA' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Выбрать PH025' }));
  await screen.findByText(/Установлено: 1.2.22-dev/);
}

it('inspects a canary target without auto-dispatch and requires explicit consent', async () => {
  await open();
  expect(screen.getByRole('button', { name: 'Разрешить обновление' })).toBeDisabled();
  expect(screen.getByText(/пакет и сертификат.*не предоставлены/i)).toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});
it('submits one exact target/digest/deadline and never calls publication or a bulk action', async () => {
  await open();
  fireEvent.click(screen.getByRole('checkbox', { name: /Подтверждаю совместимость/ }));
  const button = screen.getByRole('button', { name: 'Разрешить обновление' });
  fireEvent.click(button); fireEvent.click(button);
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(api.post).toHaveBeenCalledWith('/updates/recovery', { device_id: id, sha256: digest, duration_seconds: 600 });
  expect(await screen.findByText(/Разрешение сохранено/)).toHaveTextContent('не подтверждает установку');
});
it('keeps an offline target separate from installation and permits only a bounded permission', async () => {
  device = target({ status: 'offline', last_heartbeat: null });
  await open();
  expect(screen.getByText(/Устройство не в сети/)).toBeInTheDocument();
  expect(screen.queryByText('Установка и heartbeat подтверждены')).not.toBeInTheDocument();
});
it('exposes page two of the device registry', async () => {
  render(<UpdatesPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Адресное OTA' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Следующие устройства' }));
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/devices', expect.objectContaining({ params: { page: 2, per_page: 50, search: undefined } })));
});
it('rejects a recovery response belonging to another device', async () => {
  recovery.device_id = '33333333-3333-4333-8333-333333333333';
  await open();
  expect(await screen.findByText(/Не удалось проверить состояние OTA/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Разрешить обновление' })).toBeDisabled();
});
it('does not turn an older completed receipt into success for the selected release', async () => {
  recovery = { device_id: id, state: 'completed', active: null, observed_at: now(), recent_results: [],
    last_result: { ...grant(), sha256: 'b'.repeat(64), version_code: 10230, status: 'completed', failure_code: null,
      installed_version_code: 10230, recorded_at: now(), recovered_after_process_restart: false } };
  await open();
  expect(screen.getByText(/Результат относится к другому APK/)).toBeInTheDocument();
  expect(screen.queryByText('Установка и heartbeat подтверждены')).not.toBeInTheDocument();
});
it('waits for fresh matching version and heartbeat after a completed receipt', async () => {
  recovery = { device_id: id, state: 'completed', active: null, observed_at: now(), recent_results: [],
    last_result: { ...grant(), status: 'completed', failure_code: null, installed_version_code: 10240,
      recorded_at: now(), recovered_after_process_restart: true } };
  await open();
  expect(screen.getByText(/Установка сообщена.*ожидаем.*heartbeat/)).toBeInTheDocument();
  expect(screen.queryByText('Установка и heartbeat подтверждены')).not.toBeInTheDocument();
});
it('separates retained terminal receipts from a currently confirmed install', async () => {
  const recorded = new Date(Date.now() - 5000).toISOString();
  device = target({ agent_version: '1.2.40-dev', agent_version_code: 10240 });
  recovery = { device_id: id, state: 'completed', active: null, observed_at: now(), recent_results: [],
    last_result: { ...grant(), status: 'completed', failure_code: null, installed_version_code: 10240,
      recorded_at: recorded, recovered_after_process_restart: true } };
  render(<UpdatesPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Адресное OTA' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Выбрать PH025' }));
  expect(await screen.findByText('Установка и heartbeat подтверждены')).toBeInTheDocument();
});
it('redispatches the same grant without creating or extending another permission', async () => {
  recovery = { device_id: id, state: 'active', active: grant(), last_result: null, recent_results: [], observed_at: now() };
  await open();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить доставку' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/updates/recovery/' + id + '/dispatch', { command_id: command }));
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('confirms revoke with the captured command ID and retains receipt history', async () => {
  recovery = { device_id: id, state: 'active', active: grant(), last_result: null, recent_results: [], observed_at: now() };
  await open();
  fireEvent.click(screen.getByRole('button', { name: 'Отозвать разрешение' }));
  expect(api.delete).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить отзыв' }));
  await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/updates/recovery/' + id, { params: { command_id: command } }));
});
it('provides read-only status to a viewer and hides grant/revoke actions', async () => {
  useAuthStore.setState({ user: { id: 'viewer', org_id: 'tenant', role: 'viewer', email: 'viewer@example.test' } });
  render(<UpdatesPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Состояние OTA' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Выбрать PH025' }));
  await screen.findByText(/Установлено: 1.2.22-dev/);
  expect(screen.queryByRole('button', { name: 'Разрешить обновление' })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});
it('blocks duplicate permission after an uncertain write and displays no server exception text', async () => {
  jest.mocked(api.post).mockRejectedValue({ response: { status: 500, data: { detail: 'private-token-text' } } });
  await open();
  fireEvent.click(screen.getByRole('checkbox', { name: /Подтверждаю совместимость/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Разрешить обновление' }));
  expect(await screen.findByText(/Результат запроса неизвестен/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Разрешить обновление' })).toBeDisabled();
  expect(screen.queryByText(/private-token-text/)).not.toBeInTheDocument();
});
it('retires a late mutation result on session change', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.post).mockReturnValue(new Promise(done => { resolve = done; }) as never);
  await open();
  fireEvent.click(screen.getByRole('checkbox', { name: /Подтверждаю совместимость/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Разрешить обновление' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  act(() => useAuthStore.setState({ user: null, sessionVersion: 2 }));
  await act(async () => resolve({ status: 201, data: { device_id: id, ...grant(), delivery_hint: 'wake_published' } }));
  expect(screen.queryByText(/Разрешение сохранено/)).not.toBeInTheDocument();
});

it('rejects a grant receipt for a different digest without claiming success', async () => {
  jest.mocked(api.post).mockResolvedValue({ status: 201, data: { device_id: id, ...grant(), sha256: 'b'.repeat(64), delivery_hint: 'wake_published' } } as never);
  await open();
  fireEvent.click(screen.getByRole('checkbox', { name: /Подтверждаю совместимость/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Разрешить обновление' }));
  expect(await screen.findByText(/Результат запроса неизвестен/)).toBeInTheDocument();
  expect(screen.queryByText(/Разрешение сохранено/)).not.toBeInTheDocument();
});
it('does not offer dispatch of an expired grant', async () => {
  const stale = { ...grant(), created_at: Math.floor(Date.now() / 1000) - 120, expires_at: Math.floor(Date.now() / 1000) - 60 };
  recovery = { device_id: id, state: 'expired', active: stale, last_result: null, recent_results: [], observed_at: now() };
  await open();
  expect(screen.getByText('Срок разрешения истёк')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Повторить доставку' })).not.toBeInTheDocument();
});
it('displays a classified failure separately from confirmed installation', async () => {
  recovery = { device_id: id, state: 'failed', active: null, observed_at: now(), recent_results: [],
    last_result: { ...grant(), status: 'failed', failure_code: 'timeout', installed_version_code: null,
      recorded_at: now(), recovered_after_process_restart: false } };
  await open();
  expect(screen.getByText(/Android сообщил ошибку/)).toHaveTextContent('timeout');
  expect(screen.queryByText('Установка и heartbeat подтверждены')).not.toBeInTheDocument();
});
it('requires a fresh post-result heartbeat even when the reported package version matches', async () => {
  device = target({ agent_version: '1.2.40-dev', agent_version_code: 10240, last_heartbeat: new Date(Date.now() - 120_000).toISOString() });
  recovery = { device_id: id, state: 'completed', active: null, observed_at: now(), recent_results: [],
    last_result: { ...grant(), status: 'completed', failure_code: null, installed_version_code: 10240,
      recorded_at: new Date(Date.now() - 5000).toISOString(), recovered_after_process_restart: true } };
  render(<UpdatesPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Адресное OTA' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Выбрать PH025' }));
  expect(await screen.findByText(/Установка сообщена.*ожидаем.*heartbeat/)).toBeInTheDocument();
  expect(screen.queryByText('Установка и heartbeat подтверждены')).not.toBeInTheDocument();
});
it('blocks cached controls after a status refresh fails', async () => {
  await open();
  const previous = jest.mocked(api.get).getMockImplementation()!;
  jest.mocked(api.get).mockImplementation((url, options) => url === '/updates/recovery/' + id ? Promise.reject(new Error('network')) : previous(url, options));
  fireEvent.click(screen.getByRole('button', { name: 'Обновить состояние' }));
  expect(await screen.findByText(/Не удалось проверить состояние OTA/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Разрешить обновление' })).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});
it('does not offer an addressed managed grant for an external artifact URL', async () => {
  jest.mocked(api.get).mockResolvedValue({ data: { releases: [{ ...release, download_url: 'https://external.invalid/agent.apk' }], total: 1 } } as never);
  render(<UpdatesPage />, { wrapper: createWrapper() });
  await screen.findByText('v1.2.40-dev');
  expect(screen.queryByRole('button', { name: 'Адресное OTA' })).not.toBeInTheDocument();
});
