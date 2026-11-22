// Offline observations with the real pages and capability boundary.
const React = require('react');
const { act, fireEvent, render, screen, waitFor, within } = require('@testing-library/react');

const query = new URLSearchParams('device_id=fixture-device');
jest.mock('next/navigation', () => ({ useSearchParams: () => query, useRouter: () => ({ replace: jest.fn() }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

const { toast } = require('sonner');
const { api } = require('@/lib/api');
const { createWrapper } = require('@/__tests__/helpers');
const { useAuthStore } = require('@/lib/store');
const { CapabilitiesProvider, RouteAccessBoundary } = require('@/src/features/access/Capabilities');
const LogsPage = require('@/app/(dashboard)/logs/page').default;
const TaskPage = require('@/app/(dashboard)/tasks/[id]/page').default;
const OrchestrationPage = require('@/app/(dashboard)/orchestration/page').default;

const actor = { id: 'fixture-viewer', org_id: 'fixture-org', role: 'viewer', email: 'viewer@example.invalid' };
const device = { id: 'fixture-device', name: 'Fixture Android', status: 'online', group_ids: [], location_ids: [] };
const date = '2026-11-11T00:00:00Z';
const task = { id: 'fixture-task', org_id: actor.org_id, status: 'running', script_id: 'fixture-script',
  script_version_id: 'fixture-version', device_id: device.id, priority: 5, created_at: date, updated_at: date,
  started_at: date, finished_at: null, result: null, input_params: null };
const grants = ['device:read', 'script:read', 'pipeline:read', 'schedule:read'];
const fixtureLine = 'Fixture log survives deletion';

beforeEach(() => {
  jest.resetAllMocks();
  useAuthStore.setState({ user: actor, sessionVersion: 1 });
  api.get.mockImplementation(async url => {
    if (url === '/auth/capabilities') return { data: { schema_version: 1, user_id: actor.id, org_id: actor.org_id, role: actor.role, permissions: grants } };
    if (url === '/devices') return { data: { items: [device], page: 1, per_page: 100, pages: 1, total: 1 } };
    if (url === `/devices/${device.id}`) return { data: device };
    if (url.startsWith(`/logs/${device.id}?`)) return { data: { device_id: device.id, lines: [fixtureLine], total: 1 } };
    if (url === `/tasks/${task.id}`) return { data: task };
    if (url.startsWith(`/tasks/${task.id}/`)) return { data: [] };
    return { data: { items: [], page: 1, per_page: 100, pages: 0, total: 0 } };
  });
});

it('WEB-13: a 204 is displayed as confirmed deletion until the retained log is read again', async () => {
  api.delete.mockResolvedValue({ status: 204 });
  render(React.createElement(LogsPage), { wrapper: createWrapper() });
  await screen.findByText(fixtureLine);
  fireEvent.click(screen.getByRole('button', { name: 'Очистить логи' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Удалить логи' }));
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Логи устройства Fixture Android удалены'));
  expect(screen.queryByText(fixtureLine)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Обновить логи' }));
  expect(await screen.findByText(fixtureLine)).toBeVisible();
  expect(api.delete).toHaveBeenCalledTimes(1);
});

it.each([
  ['/logs', LogsPage, {}, 'Очистить логи'],
  ['/tasks/fixture-task', TaskPage, { params: Promise.resolve({ id: task.id }) }, 'Остановить задание'],
  ['/orchestration', OrchestrationPage, {}, 'Новый Pipeline'],
])('WEB-14: %s offers an enabled write control for a verified read-only viewer', async (pathname, Page, props, label) => {
  await act(async () => {
    const content = React.createElement(React.Suspense, { fallback: 'Loading' }, React.createElement(Page, props));
    const boundary = React.createElement(RouteAccessBoundary, { pathname }, content);
    render(React.createElement(CapabilitiesProvider, {}, boundary), { wrapper: createWrapper() });
    await props.params;
  });
  const button = await screen.findByRole('button', { name: label });
  await waitFor(() => expect(button).toBeEnabled());
  expect(api.get).toHaveBeenCalledWith('/auth/capabilities', expect.any(Object));
  expect(api.post).not.toHaveBeenCalled();
  expect(api.delete).not.toHaveBeenCalled();
});
