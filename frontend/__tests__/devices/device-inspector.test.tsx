import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '@/lib/api';
import { createTestQueryClient, createWrapper } from '../helpers';
import { DeviceInspectorDetail } from '@/src/features/devices/DeviceInspectorDetail';
// Presence pulses are exercised separately; this suite verifies device commands.
jest.mock('@/src/features/devices/DeviceViewerPresence', () => ({ DeviceViewerPresence: () => null }));
import { DeviceHistoryPanel, validateDeviceHistory, validateDeviceDiagnostics, validateDeviceLogs } from '@/src/features/devices/DeviceOperationsPanels';
import { validateDeviceSnapshot } from '@/lib/hooks/useDeviceSnapshot';
import { toast } from 'sonner';

let mockCan = (_permission: string) => true;
jest.mock('@/src/features/access/Capabilities', () => ({
  useCapabilities: () => ({ can: (permission: string) => mockCan(permission) }),
  PermissionNotice: () => <p role="status">Файловые операции недоступны для вашей роли.</p>,
}));

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock('@/components/sphere/DeviceStream', () => ({ DeviceStream: () => <div>Fixture stream</div> }));
jest.mock('@/src/features/devices/WebTerminal', () => ({ WebTerminal: () => null }));
jest.mock('@/src/features/devices/LogcatViewer', () => ({ LogcatViewer: () => null }));
jest.mock('@/src/features/devices/RunScriptTab', () => ({ RunScriptTab: () => null }));
const mockGet = api.get as jest.Mock;
const mockPost = api.post as jest.Mock;
const device = { id: 'dev-1', name: 'Remote A', status: 'busy', agent_version: '1.2.34', agent_version_code: 10234, last_seen: '2026-09-30T01:02:03Z' };
beforeEach(() => {
  mockCan = () => true; jest.clearAllMocks(); mockGet.mockResolvedValue({ data: device }); });

it('fetches by ID and keeps live controls disabled for an unconfirmed busy snapshot', async () => {
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  expect(await screen.findByText('Remote A')).toBeInTheDocument();
  expect(mockGet).toHaveBeenCalledWith('/devices/dev-1', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Видеопоток' })).toBeEnabled());
  expect(screen.getByText('Последний heartbeat APK').nextSibling).toHaveTextContent('Не сообщено');
  expect(screen.getByText('Последний контакт в каталоге').nextSibling).toHaveTextContent('UTC');
  expect(screen.getByText('CPU').nextSibling).toHaveTextContent('Не сообщено');
  expect(screen.getByText('Нет подтверждённой активной связи')).toBeInTheDocument();
  expect(screen.getByText('Неизвестно')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Перезагрузка' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Терминал' })).toBeDisabled();
  expect(mockPost).not.toHaveBeenCalled();
});

it('marks a cached snapshot and blocks commands when a later refresh fails', async () => {
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  await screen.findByText('Remote A');
  mockGet.mockRejectedValueOnce(new Error('unreachable'));
  fireEvent.click(screen.getByRole('button', { name: 'Обновить карточку' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('сохранённый ответ');
  expect(screen.getByRole('button', { name: 'Перезагрузка' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Видеопоток' })).toBeEnabled();
});

it('shows the APK VPN receipt and does not promote a legacy ADB flag into observed access', async () => {
  const observed = new Date().toISOString();
  mockGet.mockResolvedValue({ data: { ...device, last_heartbeat: observed, adb_connected: true, vpn_active: false,
    vpn_observation_state: 'fresh', vpn_observation_max_age_seconds: 120, vpn_observed_at: observed } });
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  const vpn = (await screen.findByText('VPN, активность по APK')).nextSibling as HTMLElement;
  expect(vpn).toHaveTextContent('Не активен');
  expect(vpn.querySelector('time')).toHaveAttribute('datetime', observed);
  expect(screen.getByText('ADB (дополнительный канал)').nextSibling).toHaveTextContent('Не подтверждён');
  expect(screen.getByRole('button', { name: 'Перезагрузка' })).toBeEnabled();
});

it('opens the separately authorized stream while the catalogue reports a disconnected agent', async () => {
  mockGet.mockResolvedValue({ data: { ...device, status: 'offline' } });
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  await screen.findByText('Remote A');
  expect(screen.getByRole('button', { name: 'Перезагрузка' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Видеопоток' }));
  expect(await screen.findByText('Fixture stream')).toBeInTheDocument();
  expect(mockPost).not.toHaveBeenCalled();
});

it('still denies stream access when the role lacks stream permission', async () => {
  mockCan = permission => permission !== 'stream:read';
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  await screen.findByText('Remote A');
  fireEvent.click(screen.getByRole('button', { name: 'Видеопоток' }));
  expect(screen.getByRole('button', { name: 'Видеопоток' })).toBeDisabled();
  expect(screen.queryByText('Fixture stream')).not.toBeInTheDocument();
});

it('does not use a cached online card to enable commands before revalidation', async () => {
  const qc = createTestQueryClient();
  qc.setQueryData(['devices', 'dev-1'], device);
  mockGet.mockImplementationOnce(() => new Promise(() => {}));
  const { unmount } = render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper(qc) });
  expect(screen.getByRole('button', { name: 'Перезагрузка' })).toBeDisabled();
  unmount(); qc.clear();
});

it('shows API failure instead of an empty or fabricated device', async () => {
  mockGet.mockRejectedValueOnce(new Error('404'));
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  expect(await screen.findByRole('alert')).toHaveTextContent('Карточка устройства недоступна');
  expect(screen.queryByRole('button', { name: 'Видеопоток' })).not.toBeInTheDocument();
});

it('makes history requests only for the selected tab and device', async () => {
  const user = userEvent.setup();
  mockGet.mockImplementation(async (url: string) => ({ data: url === '/tasks' ? { items: [{ id: 'task-1', device_id: 'dev-1', status: 'completed', created_at: '2026-09-30T00:00:00Z', script_name: 'Read-only canary' }], total: 7 } : device }));
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  await screen.findByText('Remote A');
  expect(mockGet).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole('tab', { name: 'Задачи' }));
  expect(await screen.findByText('Read-only canary')).toBeInTheDocument();
  expect(mockGet).toHaveBeenCalledWith('/tasks', expect.objectContaining({ params: expect.objectContaining({ device_id: 'dev-1', per_page: 6 }) }));
  expect(screen.getByRole('link', { name: 'Результат и шаги задачи' })).toHaveAttribute('href', '/tasks/task-1');
});

it('links from the saved APK logs to the archive for the same offline device', async () => {
  const user = userEvent.setup();
  mockGet.mockImplementation(async (url: string) => ({ data: url === '/logs/dev-1'
    ? { device_id: 'dev-1', lines: ['offline saved log'] }
    : { ...device, status: 'offline' } }));
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  await screen.findByText('Remote A');
  expect(mockGet).not.toHaveBeenCalledWith('/logs/dev-1', expect.anything());
  await user.click(screen.getByRole('tab', { name: 'Логи APK' }));
  expect(await screen.findByText('offline saved log')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Открыть архив журналов' })).toHaveAttribute('href', '/logs?device_id=dev-1');
  expect(mockGet).toHaveBeenCalledWith('/logs/dev-1', expect.objectContaining({ params: { lines: 100 } }));
  expect(mockPost).not.toHaveBeenCalled();
});

it('ignores a late response after switching to another device', async () => {
  let finishFirst!: (data: unknown) => void;
  mockGet.mockImplementation((url: string) => url === '/devices/dev-1' ? new Promise((resolve) => { finishFirst = resolve; }) : Promise.resolve({ data: { ...device, id: 'dev-2', name: 'Remote B' } }));
  const { rerender } = render(<DeviceInspectorDetail key="dev-1" deviceId="dev-1" />, { wrapper: createWrapper() });
  rerender(<DeviceInspectorDetail key="dev-2" deviceId="dev-2" />);
  await screen.findByText('Remote B');
  await act(async () => finishFirst({ data: device }));
  expect(screen.queryByText('Remote A')).not.toBeInTheDocument();
});

it('requires confirmation and sends one reboot without treating timeout as success', async () => {
  mockGet.mockResolvedValue({ data: { ...device, last_heartbeat: new Date().toISOString() } });
  const user = userEvent.setup();
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  await screen.findByText('Remote A');
  await user.click(screen.getByRole('button', { name: 'Перезагрузка' }));
  expect(mockPost).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Отмена' }));
  expect(mockPost).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Перезагрузка' }));
  let rejectCommand!: (error: Error) => void;
  mockPost.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectCommand = reject; }));
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить перезагрузку' }));
  expect(screen.getByRole('button', { name: 'Ожидаем ответ…' })).toBeDisabled();
  await act(async () => rejectCommand(new Error('timeout')));
  expect(mockPost).toHaveBeenCalledTimes(1);
  expect(toast.success).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith('Не удалось подтвердить перезагрузку', expect.any(Object));
});

it('rejects records for another device instead of showing a misleading history', async () => {
  mockGet.mockResolvedValue({ data: { items: [{ id: 'task', device_id: 'other', status: 'completed', created_at: 'now' }], total: 1 } });
  render(<DeviceHistoryPanel deviceId="dev-1" kind="tasks" />, { wrapper: createWrapper() });
  expect(await screen.findByRole('alert')).toHaveTextContent('не означает отсутствие записей');
  expect(screen.queryByText('API не вернул записей для этого устройства.')).not.toBeInTheDocument();
});

it('validates device identity and separates missing metadata from zero counters', () => {
  expect(() => validateDeviceSnapshot({ ...device, id: 'other' }, 'dev-1')).toThrow();
  expect(() => validateDeviceHistory({ items: null, total: 0 }, 'dev-1', 'tasks')).toThrow();
  expect(() => validateDeviceDiagnostics({ device_id: 'other', state: 'active_report' }, 'dev-1')).toThrow();
  expect(() => validateDeviceLogs({ device_id: 'other', lines: [] }, 'dev-1')).toThrow();
  expect(validateDeviceSnapshot({ ...device, status: 'future_status', battery_level: 0 }, 'dev-1')).toMatchObject({ status: 'unknown', battery_level: 0 });
});


it('keeps a viewer card readable while disabling root mutations and reboot', async () => {
  mockCan = permission => permission === 'device:read' || permission === 'stream:read';
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  await screen.findByText('Remote A');
  expect(screen.getByRole('button', { name: 'Видеопоток' })).toBeEnabled();
  for (const name of ['Перезагрузка', 'Терминал', 'Shell-скрипт']) {
    expect(screen.getByRole('button', { name })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name }));
  }
  expect(mockPost).not.toHaveBeenCalled();
});

it('opens Files without reading the device folder when the role lacks device:write', async () => {
  mockCan = permission => permission !== 'device:write';
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  await userEvent.click(await screen.findByRole('tab', { name: 'Файлы' }));
  expect(await screen.findByText('Файловые операции недоступны для вашей роли.')).toBeInTheDocument();
  expect(mockGet).not.toHaveBeenCalledWith('/devices/dev-1/files', expect.anything());
});

it('opens Files from the ordinary device card when the agent is reachable', async () => {
  const observed = new Date().toISOString();
  mockGet.mockImplementation(async url => ({
    data: url === '/devices/dev-1/files' ? { version: 1, max_bytes: 262144, files: [] }
      : { ...device, last_heartbeat: observed },
  }));
  render(<DeviceInspectorDetail deviceId="dev-1" />, { wrapper: createWrapper() });
  await userEvent.click(await screen.findByRole('tab', { name: 'Файлы' }));
  expect(await screen.findByText('Рабочая папка пока пуста.')).toBeInTheDocument();
  expect(mockGet).toHaveBeenCalledWith('/devices/dev-1/files', expect.objectContaining({ signal: expect.any(AbortSignal) }));
});
