const React = require('react');
const { act, cleanup, fireEvent, render, screen, waitFor } = require('@testing-library/react');
const { createTestQueryClient, createWrapper } = require('@/__tests__/helpers');

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useDeviceSnapshot', () => ({ useDeviceSnapshot: () => ({ data: { id: 'fixture-device', name: 'Fixture device' } }) }));
jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: () => ({ data: { items: [] } }) }));
jest.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams('device_id=fixture-device'),
  useRouter: () => ({ replace: jest.fn() }),
}));

const { api } = require('@/lib/api');
const { RecoveryDialog } = require('@/src/features/updates/RecoveryDialog');
const LogsPage = require('@/app/(dashboard)/logs/page').default;
const TaskDetailPage = require('@/app/(dashboard)/tasks/[id]/page').default;

beforeEach(() => jest.resetAllMocks());

it('shows a previous failure as the result of a newer pending OTA for the same release', async () => {
  const id = '11111111-1111-4111-8111-111111111111';
  const oldId = '22222222-2222-4222-8222-222222222222';
  const activeId = '33333333-3333-4333-8333-333333333333';
  const digest = 'a'.repeat(64);
  const release = { id: 'ota-release', platform: 'android-canary', flavor: 'dev', sha256: digest,
    download_url: `/api/v1/updates/artifacts/${digest}`, version_name: '1.2.40-dev', version_code: 10240 };
  const now = new Date().toISOString();
  const second = Math.floor(Date.now() / 1000);
  const device = { id, name: 'Fixture APK', is_active: true, status: 'online', agent_version_code: 10222, last_heartbeat: now };
  const active = { command_id: activeId, sha256: digest, version_name: release.version_name, version_code: 10240,
    created_at: second, expires_at: second + 600 };
  const failed = { command_id: oldId, sha256: digest, version_name: release.version_name, version_code: 10240,
    status: 'failed', failure_code: 'install_failed', installed_version_code: null, recovered_after_process_restart: false,
    recorded_at: new Date(Date.now() - 10_000).toISOString() };
  api.get.mockImplementation(async url => {
    if (url === '/devices') return { data: { items: [device], total: 1, page: 1, pages: 1, per_page: 50 } };
    if (url === `/devices/${id}`) return { data: device };
    if (url === `/updates/recovery/${id}`) return { data: { device_id: id, state: 'active', active,
      last_result: failed, recent_results: [failed], observed_at: now } };
    throw Error(`Unexpected GET ${url}`);
  });
  render(React.createElement(RecoveryDialog, { release, scope: 'fixture', available: true, canManage: true, onClose: jest.fn() }),
    { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Выбрать Fixture APK' }));
  expect(await screen.findByText('Ожидается результат Android')).toBeInTheDocument();
  expect(screen.getByText(`Команда: ${activeId}`)).toBeInTheDocument();
  const alert = screen.getByRole('alert');
  expect(alert).toHaveTextContent('Android сообщил ошибку: install_failed');
  expect(alert).not.toHaveTextContent(oldId);
  expect(screen.getByText(oldId).closest('details')).toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('hides available live steps when a failed APK result contains only an error', async () => {
  const id = 'task-a';
  const ts = '2026-11-13T10:00:00Z';
  let task = { id, status: 'running', script_id: 'script-id', device_id: 'device-id', script_name: 'Audit fixture',
    result: null, error_message: null, created_at: ts, started_at: ts, updated_at: ts, finished_at: null };
  const entry = { node_id: 'fixture-node-before-disconnect', nodes_done: 7, ts: Date.parse(ts) / 1000 };
  api.get.mockImplementation(async url => {
    if (url === `/tasks/${id}`) return { data: task };
    if (url === `/tasks/${id}/progress`) return { data: { nodes_done: 7, total_nodes: 10, cycles: 1 } };
    if (url === `/tasks/${id}/live-logs`) return { data: [entry] };
    if (url === `/tasks/${id}/logs`) return { data: [] };
    throw Error(`Unexpected GET ${url}`);
  });
  const view = async client => {
    const params = Promise.resolve({ id });
    await act(async () => {
      render(React.createElement(React.Suspense, { fallback: 'Loading' },
        React.createElement(TaskDetailPage, { params })), { wrapper: createWrapper(client) });
      await params;
    });
  };
  const client = createTestQueryClient();
  await view(client);
  expect(await screen.findByText(entry.node_id)).toBeInTheDocument();
  task = { ...task, status: 'failed', finished_at: ts, error_message: 'execution_outcome_unknown_after_restart',
    result: { success: false, error: 'execution_outcome_unknown_after_restart' } };
  await act(async () => client.setQueryData(['tasks', id], task));
  expect(await screen.findByText('Отчёты шагов не получены.')).toBeInTheDocument();
  expect(screen.queryByText(entry.node_id)).not.toBeInTheDocument();
  expect(client.getQueryData(['tasks', id, 'live-logs'])).toEqual([entry]);
  cleanup();
  api.get.mockClear();
  await view(createTestQueryClient());
  expect(await screen.findByText('Отчёты шагов не получены.')).toBeInTheDocument();
  expect(api.get.mock.calls.some(([url]) => url.endsWith('/live-logs'))).toBe(false);
});

it('renders a busy journal and an unavailable log source with the same 503 explanation', async () => {
  const options = [
    { detail: 'Log read capacity is busy', headers: { 'retry-after': '1', 'x-request-id': 'fixture-busy' } },
    { detail: 'Log source is unavailable', headers: { 'x-request-id': 'fixture-unavailable' } },
  ];
  for (const { detail, headers } of options) {
    api.get.mockRejectedValue({ message: 'Request failed with status code 503', response: { status: 503, data: { detail }, headers } });
    render(React.createElement(LogsPage), { wrapper: createWrapper() });
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Логи не загружены: Request failed with status code 503');
    expect(alert).not.toHaveTextContent(detail);
    expect(alert).not.toHaveTextContent(headers['x-request-id']);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Повторить запрос' })).toBeEnabled());
    cleanup();
  }
});
