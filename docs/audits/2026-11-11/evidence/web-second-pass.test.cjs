// Audit observations using the real pages and React Query hooks with an offline HTTP fixture.
const React = require('react');
const { act, fireEvent, render, screen, waitFor, within } = require('@testing-library/react');

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/components/sphere/DeviceStream', () => ({ DeviceStream: () => null }));
jest.mock('@/components/sphere/DeviceSearchSelect', () => ({
  DeviceSearchSelect: ({ onChange, excludedIds, disabled }) => require('react').createElement('button', {
    type: 'button', disabled: disabled || excludedIds?.has('fixture-device'), onClick: () => onChange('fixture-device'),
  }, 'Выбрать тестовое устройство'),
}));

const FleetStreamPage = require('@/app/(dashboard)/stream/page').default;
const TaskDetailPage = require('@/app/(dashboard)/tasks/[id]/page').default;
const { VpnRouterInfrastructure } = require('@/src/features/vpn/VpnRouterInfrastructure');
const { createWrapper } = require('@/__tests__/helpers');
const { useAuthStore } = require('@/lib/store');
const { api } = require('@/lib/api');

const date = '2026-11-11T00:00:00Z';
const device = name => ({ id: name, name, status: 'online', group_ids: [], location_ids: [] });
const source = {
  id: 'task-original', org_id: 'fixture-org', status: 'completed', script_id: 'script',
  script_version_id: 'version-1', device_id: 'fixture-device', priority: 5,
  created_at: date, updated_at: date, started_at: date, finished_at: date,
  result: null, error_message: null, input_params: {},
};

beforeEach(() => jest.resetAllMocks());

it('WEB-10: resets an uncached stream catalog page while its request is still pending', async () => {
  const first = { items: ['One', 'Two', 'Three', 'Four'].map(device), page: 1, per_page: 4, pages: 2, total: 5 };
  const second = { ...first, items: [device('Only second page')], page: 2 };
  let replyPageTwo;
  let pageTwoSignal;
  api.get.mockImplementation((url, options) => {
    if (url !== '/devices') return Promise.resolve({ data: [] });
    if (options.params.page !== 2) return Promise.resolve({ data: first });
    pageTwoSignal = options.signal;
    return new Promise(resolve => { replyPageTwo = resolve; });
  });
  render(React.createElement(FleetStreamPage), { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Следующая страница' }));
  await waitFor(() => expect(api.get.mock.calls.some(([url, options]) => url === '/devices' && options.params.page === 2)).toBe(true));
  await waitFor(() => expect(pageTwoSignal.aborted).toBe(true));
  await act(async () => replyPageTwo({ data: second }));
  expect(screen.queryByText('Only second page')).not.toBeInTheDocument();
  expect(screen.getByText('1 / 2')).toBeInTheDocument();
});

it('WEB-11: after a lost rerun receipt the UI invites a second create request', async () => {
  api.get.mockImplementation(async url => ({ data: url === '/tasks/task-original' ? source : [] }));
  const fixtureExecutions = [];
  api.post.mockImplementation(async () => {
    const id = `fixture-run-${fixtureExecutions.length + 1}`;
    // Model a first rerun already completed by the time the operator sees the timeout.
    const status = fixtureExecutions.length ? 'queued' : 'completed';
    fixtureExecutions.push({ id, status });
    if (fixtureExecutions.length === 1) throw new Error('Response lost after first execution');
    return { data: { id, status } };
  });
  const params = Promise.resolve({ id: source.id });
  await act(async () => {
    render(React.createElement(React.Suspense, { fallback: 'Loading' }, React.createElement(TaskDetailPage, { params })), { wrapper: createWrapper() });
    await params;
  });
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить выполнение' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Команда не выполнена. Проверьте связь и права доступа, затем повторите действие.');
  const retry = screen.getByRole('button', { name: 'Повторить выполнение' });
  expect(retry).toBeEnabled();
  expect(api.get.mock.calls.map(([url]) => url).every(url => ['/tasks/task-original', '/tasks/task-original/logs'].includes(url))).toBe(true);
  fireEvent.click(retry);
  expect(await screen.findByRole('link', { name: 'Открыть новое задание' })).toHaveAttribute('href', '/tasks/fixture-run-2');
  expect(api.post.mock.calls).toEqual([['/tasks/task-original/rerun'], ['/tasks/task-original/rerun']]);
});

it('WEB-12: reopening VPN assignment permits retry for the same unresolved device', async () => {
  useAuthStore.setState({ user: { id: 'fixture-admin', org_id: 'fixture-org', role: 'org_admin' }, sessionVersion: 1 });
  api.get.mockImplementation(async url => ({ data: url === '/vpn/peers' ? [] : {} }));
  api.post.mockRejectedValue(new Error('VPN assignment receipt lost'));
  render(React.createElement(VpnRouterInfrastructure), { wrapper: createWrapper() });

  async function openProvision() {
    const add = screen.getByRole('button', { name: 'Назначить peer' });
    await waitFor(() => expect(add).toBeEnabled());
    fireEvent.click(add);
    const dialog = within(await screen.findByRole('dialog', { name: 'Назначение адреса из пула' }));
    fireEvent.click(dialog.getByRole('button', { name: 'Выбрать тестовое устройство' }));
    return dialog;
  }

  const first = await openProvision();
  fireEvent.click(first.getByRole('button', { name: 'Назначить адрес' }));
  await first.findByText(/Результат неизвестен/);
  expect(first.getByRole('button', { name: 'Назначить адрес' })).toBeDisabled();
  fireEvent.click(first.getByRole('button', { name: 'Закрыть' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByText(/Новые операции для них заблокированы/)).toBeVisible();
  const second = await openProvision();
  const submit = second.getByRole('button', { name: 'Назначить адрес' });
  expect(submit).toBeEnabled();
  fireEvent.click(submit);
  await waitFor(() => expect(api.post.mock.calls).toEqual([
    ['/vpn/assign', { device_id: 'fixture-device' }], ['/vpn/assign', { device_id: 'fixture-device' }],
  ]));
});
