// Offline proof against the current Tasks page and its real React Query hooks.
const React = require('react');
const { fireEvent, render, screen, waitFor, within } = require('@testing-library/react');

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

const { api } = require('@/lib/api');
const { toast } = require('sonner');
const { createWrapper } = require('@/__tests__/helpers');
const TasksPage = require('@/app/(dashboard)/tasks/page').default;
const AccountsPage = require('@/app/(dashboard)/accounts/page').default;
const OrchestrationPage = require('@/app/(dashboard)/orchestration/page').default;

const createdAt = '2026-11-13T00:00:00Z';
const batchId = '11111111-1111-4111-8111-111111111111';
const otherBatchId = '22222222-2222-4222-8222-222222222222';

function page(rows, pageNumber, pageSize) {
  const start = (pageNumber - 1) * pageSize;
  return { items: rows.slice(start, start + pageSize), total: rows.length, page: pageNumber, per_page: pageSize, pages: Math.ceil(rows.length / pageSize) };
}

function mockTransport(batchSize) {
  const common = { org_id: 'fixture-org', script_id: 'fixture-script', device_id: 'fixture-device',
    status: 'queued', priority: 5, created_at: createdAt, updated_at: createdAt };
  const other = { ...common, id: 'fixture-other-task', batch_id: otherBatchId, script_name: 'Unrelated run' };
  const targetRows = Array.from({ length: batchSize }, (_, index) => ({
    ...common, id: `fixture-task-${index}`, batch_id: batchId, script_name: `Target task ${index + 1}`,
  }));
  api.get.mockImplementation(async (path, options) => {
    if (path === '/tasks') {
      const params = options?.params ?? {};
      const rows = params.batch_id === batchId ? targetRows : [other, ...targetRows];
      return { data: page(rows, params.page ?? 1, params.per_page ?? 50) };
    }
    if (path === '/devices') return { data: { items: [], total: batchSize } };
    if (path === '/scripts') return { data: { items: [{ id: 'fixture-script', name: 'Synthetic script', node_count: 2, is_archived: false }] } };
    if (path === `/batches/${batchId}`) return { data: { id: batchId, total: batchSize, status: 'pending', admission_receipts: [] } };
    return { data: page([], 1, 25) };
  });
  api.post.mockResolvedValue({ status: 202, data: { id: batchId, total: batchSize, status: 'pending', online_devices: batchSize } });
}

beforeEach(() => {
  jest.resetAllMocks();
  if (!Element.prototype.hasPointerCapture) Element.prototype.hasPointerCapture = () => false;
  if (!Element.prototype.setPointerCapture) Element.prototype.setPointerCapture = () => {};
  if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {};
});

it.each([10, 100])('batch deep link with %i targets requests global history and shows another batch', async (size) => {
  window.history.replaceState(null, '', `/tasks?batch_id=${batchId}`);
  mockTransport(size);
  render(React.createElement(TasksPage), { wrapper: createWrapper() });
  expect((await screen.findAllByText('Unrelated run')).length).toBeGreaterThan(0);
  const listRequests = api.get.mock.calls.filter(([path]) => path === '/tasks');
  expect(listRequests).toHaveLength(2);
  expect(listRequests.map(([, options]) => options.params.per_page)).toEqual(expect.arrayContaining([10, 25]));
  expect(listRequests.every(([, options]) => !options.params.batch_id)).toBe(true);
  expect(api.get.mock.calls.some(([path]) => path === `/batches/${batchId}`)).toBe(false);
  expect(await screen.findByText(`Показано 10 из ${size + 1}. В очереди, назначены или выполняются.`)).toBeInTheDocument();
});

it('broadcast replaces an explicit zero delay, labels priority 1 low, and announces a pending 202 as launched', async () => {
  window.history.replaceState(null, '', '/tasks');
  mockTransport(10);
  render(React.createElement(TasksPage), { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: /Запустить на парке/ }));
  const dialog = await screen.findByRole('dialog');
  const inputs = dialog.querySelectorAll('input[type="number"]');
  expect(inputs).toHaveLength(2);
  fireEvent.change(inputs[1], { target: { value: '0' } });
  expect(inputs[1]).toHaveValue(5000);
  const selectors = dialog.querySelectorAll('button[role="combobox"]');
  expect(selectors).toHaveLength(2);
  fireEvent.keyDown(selectors[0], { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: /Synthetic script/ }));
  fireEvent.keyDown(selectors[1], { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: '1 (низкий)' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Запустить на 10 устройствах' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/batches/broadcast', expect.objectContaining({ wave_delay_ms: 5000, priority: 1 })));
  expect(toast.success).toHaveBeenCalledWith('Батч запущен на 10 устройствах');
  expect(api.get.mock.calls.some(([path]) => path === `/batches/${batchId}`)).toBe(false);
});

it('a manually entered second game keeps the same global server choices', async () => {
  api.get.mockImplementation(async path => {
    if (path === '/game-accounts/servers') return { data: { servers: [{ id: 1, name: 'Fixture shared server' }] } };
    if (path === '/game-accounts/stats') return { data: { games: [] } };
    return { data: page([], 1, 50) };
  });
  api.post.mockResolvedValue({ data: {} });
  render(React.createElement(AccountsPage), { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Создать' }));
  const game = screen.getByPlaceholderText('com.br.top');
  expect(game).toHaveValue('com.br.top');
  fireEvent.change(game, { target: { value: 'org.fixture.secondgame' } });
  fireEvent.change(screen.getByPlaceholderText('Ivan_Petrov'), { target: { value: 'Fixture_User' } });
  fireEvent.change(screen.getByPlaceholderText('Авто-генерация если пусто'), { target: { value: 'fixture-only-value' } });
  const dialog = await screen.findByRole('dialog');
  const server = [...dialog.querySelectorAll('button[role="combobox"]')].find(element => element.textContent === 'Выберите сервер');
  expect(server).toBeDefined();
  fireEvent.keyDown(server, { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: /Fixture shared server/ }));
  fireEvent.click([...dialog.querySelectorAll('button')].find(element => element.textContent.trim() === 'Создать'));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/game-accounts', expect.objectContaining({
    game: 'org.fixture.secondgame', server_name: 'Fixture shared server',
  })));
  const serverRequests = api.get.mock.calls.filter(([path]) => path === '/game-accounts/servers');
  expect(serverRequests.length).toBeGreaterThan(0);
  expect(serverRequests.every(call => call.length === 1)).toBe(true);
});

it('the schedule script picker stops after the first 50 despite a catalog of 51', async () => {
  const scripts = Array.from({ length: 51 }, (_, index) => ({ id: `fixture-script-${index + 1}`, name: `Catalog item ${index + 1}`, is_archived: false }));
  api.get.mockImplementation(async (path, options) => ({ data: path === '/scripts'
    ? page(scripts, options?.params?.page ?? 1, options?.params?.per_page ?? 50)
    : page([], 1, 100) }));
  render(React.createElement(OrchestrationPage), { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  fireEvent.click(screen.getByRole('button', { name: 'Новое расписание' }));
  const dialog = within(screen.getByRole('dialog'));
  fireEvent.click(dialog.getByRole('button', { name: /Script/ }));
  expect(await dialog.findByRole('option', { name: /Catalog item 50/ })).toBeInTheDocument();
  expect(dialog.queryByRole('option', { name: /Catalog item 51/ })).not.toBeInTheDocument();
  expect(dialog.queryByRole('button', { name: /Следующая страница/ })).not.toBeInTheDocument();
  expect(api.get.mock.calls.some(([path, options]) => path === '/scripts' && (options?.params?.page ?? 1) > 1)).toBe(false);
});
