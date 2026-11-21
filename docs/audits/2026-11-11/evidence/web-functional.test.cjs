// Observe user-visible behavior with the real React pages and synthetic API data.
// Run with the command recorded in ../WEB.md. No request leaves this process.
const React = require('react');
const { fireEvent, render, screen, waitFor, within } = require('@testing-library/react');
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/components/sphere/DeviceSelector', () => ({
  DeviceSelector: ({ value, onChange }) => require('react').createElement('button', {
    type: 'button', onClick: () => onChange(value.length ? [] : ['fixture-device']),
  }, 'Переключить тестовую цель'),
}));

const { createWrapper } = require('@/__tests__/helpers');
const { api } = require('@/lib/api');
const AccountsPage = require('@/app/(dashboard)/accounts/page').default;
const DiscoveryPage = require('@/app/(dashboard)/discovery/page').default;
const OrchestrationPage = require('@/app/(dashboard)/orchestration/page').default;
const SessionsPage = require('@/app/(dashboard)/sessions/page').default;

const pipeline = { id: 'fixture-pipeline', name: 'Fixture pipeline', steps: [], version: 1, tags: [], is_active: true };
const schedule = {
  id: 'fixture-schedule', name: 'Fixture schedule', description: null, target_type: 'pipeline',
  pipeline_id: pipeline.id, script_id: null, cron_expression: null, interval_seconds: 3600,
  one_shot_at: null, timezone: 'UTC', conflict_policy: 'skip', is_active: true,
  device_ids: ['fixture-device'], total_runs: 0, next_fire_at: null, last_fired_at: null,
};
const date = '2026-11-11T00:00:00Z';
const account = {
  id: 'fixture-account', game: 'fixture-game', login: 'fixture_login', nickname: 'SeparateNick',
  status: 'free', gender: 'male', level: 5, total_bans: 0, total_sessions: 0,
  meta: { fixture: true }, created_at: date, updated_at: date,
};

function session(login) {
  return {
    id: `fixture-session-${login}`, account_login: login, account_game: 'fixture-game',
    device_name: 'Fixture device', device_id: 'fixture-device', started_at: date, ended_at: null,
    duration_seconds: 0, nodes_executed: 7, errors_count: 2, end_reason: null,
  };
}

function listing(items, params, total = items.length) {
  return { data: { items, page: params?.page ?? 1, per_page: params?.per_page ?? 100,
    total, pages: Math.ceil(total / (params?.per_page ?? 100)) } };
}

beforeEach(() => {
  jest.resetAllMocks();
  api.get.mockImplementation(async (url, { params } = {}) => {
    if (url === '/pipelines') return listing([pipeline], params);
    if (url === '/schedules') return listing([schedule], params);
    if (url === '/game-accounts') return listing([account], params);
    if (url === '/game-accounts/servers') return { data: { servers: [], total: 0 } };
    if (url === '/game-accounts/stats' || url === '/account-sessions/stats') return { data: null };
    if (url === '/account-sessions') {
      return listing([session(params?.page === 2 ? 'only_page_two' : 'only_page_one')], params, 51);
    }
    return listing([], params);
  });
  api.post.mockResolvedValue({ data: { id: 'created-pipeline' } });
  api.patch.mockResolvedValue({ data: account });
});

function open(Page) {
  render(React.createElement(Page), { wrapper: createWrapper() });
}

it('WEB-01: create-only issues a separate run after the target picker was used', async () => {
  open(OrchestrationPage);
  fireEvent.click(await screen.findByRole('button', { name: 'Новый Pipeline' }));
  const dialog = within(screen.getByRole('dialog'));
  fireEvent.change(dialog.getByPlaceholderText('Например: Reboot + Screenshot + Report'), { target: { value: 'Audit fixture' } });
  fireEvent.change(dialog.getByPlaceholderText('Выполнить скрипт'), { target: { value: 'Wait only' } });
  fireEvent.change(dialog.getByDisplayValue('Execute Script'), { target: { value: 'delay' } });
  fireEvent.click(dialog.getByRole('button', { name: 'Создать и запустить' }));
  fireEvent.click(dialog.getByRole('button', { name: 'Переключить тестовую цель' }));
  fireEvent.click(dialog.getByRole('button', { name: 'Создать Pipeline' }));
  await waitFor(() => expect(api.post.mock.calls.map(([url]) => url)).toEqual(['/pipelines', '/pipelines/created-pipeline/run']));
  expect(api.post.mock.calls[1][1]).toEqual({ device_id: 'fixture-device', input_params: {} });
});

it('WEB-02: clearing the last device leaves device_ids out of the serialized edit', async () => {
  api.patch.mockResolvedValue({ data: schedule });
  open(OrchestrationPage);
  fireEvent.click(await screen.findByText('Schedules'));
  await screen.findByText(schedule.name);
  fireEvent.click(screen.getByTitle('Редактировать'));
  const dialog = within(screen.getByRole('dialog'));
  fireEvent.click(dialog.getByRole('button', { name: 'Переключить тестовую цель' }));
  const save = dialog.getByRole('button', { name: 'Сохранить изменения' });
  expect(save).toBeEnabled();
  fireEvent.click(save);
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/schedules/fixture-schedule', expect.any(Object)));
  expect(JSON.parse(JSON.stringify(api.patch.mock.calls[0][1]))).not.toHaveProperty('device_ids');
});

it('WEB-03: the manual end sends only the reason even when counters are displayed', async () => {
  open(SessionsPage);
  fireEvent.click(await screen.findByRole('button', { name: 'Завершить сессию only_page_one' }));
  const dialog = within(await screen.findByRole('dialog', { name: 'Завершить активную сессию?' }));
  fireEvent.click(dialog.getByRole('button', { name: 'Завершить сессию' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/account-sessions/fixture-session-only_page_one/end', { end_reason: 'manual' }));
});

async function editAccount() {
  open(AccountsPage);
  fireEvent.click(await screen.findByTitle('Редактировать'));
  return within(await screen.findByRole('dialog', { name: 'Редактировать аккаунт' }));
}

it('WEB-04: the login edit sends the new login as the separate nickname', async () => {
  const dialog = await editAccount();
  fireEvent.change(dialog.getByDisplayValue(account.login), { target: { value: 'changed_login' } });
  fireEvent.click(dialog.getByRole('button', { name: 'Сохранить' }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/game-accounts/fixture-account', { login: 'changed_login', nickname: 'changed_login' }));
});

it('WEB-06: a syntax error in metadata silently vanishes while another edit saves', async () => {
  const dialog = await editAccount();
  fireEvent.change(dialog.getByPlaceholderText('{"emulator": "emu-1", "notes": "..."}'), { target: { value: '{' } });
  fireEvent.change(dialog.getByDisplayValue('5'), { target: { value: '6' } });
  fireEvent.click(dialog.getByRole('button', { name: 'Сохранить' }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/game-accounts/fixture-account', { level: 6 }));
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Редактировать аккаунт' })).not.toBeInTheDocument());
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('WEB-07: empty discovery result tells the operator to check the server network', async () => {
  api.post.mockResolvedValue({ data: { scanned: 4, found: 0, registered: 0, devices: [], duration_ms: 10 } });
  open(DiscoveryPage);
  fireEvent.change(screen.getByRole('textbox', { name: 'ID существующего PC Agent · UUID' }), {
    target: { value: '00000000-0000-4000-8000-000000000001' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Начать поиск' }));
  expect(await screen.findByText(/доступность сети со стороны сервера/)).toBeInTheDocument();
  expect(screen.getByText(/Сеть проверяет выбранный PC Agent/)).toBeInTheDocument();
});

it('WEB-08: local search on the second page makes a visible match disappear', async () => {
  open(SessionsPage);
  fireEvent.click(await screen.findByRole('button', { name: 'Следующая страница' }));
  await screen.findByText('only_page_two');
  fireEvent.change(screen.getByRole('textbox', { name: 'Поиск сессий на текущей странице' }), { target: { value: 'only_page_two' } });
  await waitFor(() => expect(screen.queryByText('only_page_two')).not.toBeInTheDocument());
  expect(api.get).toHaveBeenLastCalledWith('/account-sessions', { params: expect.objectContaining({ page: 1 }) });
});
