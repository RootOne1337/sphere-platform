import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { DeviceApplicationBinding, applicationBindingLabel } from '@/src/features/devices/DeviceApplicationBinding';
import { ProfileAutomationSettings } from '@/src/features/accounts/ProfileAutomationSettings';
import { createWrapper } from '../helpers';

const grants = new Set<string>();
jest.mock('@/src/features/access/Capabilities', () => ({ useCapabilities: () => ({ can: (permission: string) => grants.has(permission) }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), put: jest.fn() } }));

const first = {
  id: 'first-profile', key: 'first-game', name: 'First Game', android_package: 'dev.fixture.first',
  source: 'tenant', aliases: [], created_at: '2026-11-14T01:00:00Z', updated_at: '2026-11-14T01:00:00Z',
  servers: [{ key: 'north', name: 'North', domain: 'north.example.test', port: 1234 }],
} as const;
const second = {
  ...first, id: 'second-profile', key: 'second-game', name: 'Second Game', android_package: 'dev.fixture.second',
  servers: [{ key: 'south', name: 'South', domain: 'south.example.test', port: 5678 }],
} as const;
const builtin = { ...first, id: 'builtin', key: 'black-russia', name: 'Black Russia', source: 'builtin', created_at: null, updated_at: null };
const bindingPath = '/devices/device-1/application-binding';
const emptyBinding = { device_id: 'device-1', application_profile_id: null, application_server_key: null, revision: 0 };
const selectedBinding = { ...emptyBinding, application_profile_id: second.id, application_server_key: 'south', revision: 1 };
const policyPath = `/application-profiles/${first.id}/automation-policy`;
const emptyPolicy = {
  application_profile_id: first.id, revision: 0, registration_enabled: false, registration_script_id: null,
  max_concurrent_registrations: 3, registration_timeout_seconds: 600,
  farming_enabled: false, farming_script_id: null, max_concurrent_farming: 10,
  farming_session_duration_seconds: 3600, default_target_level: 3, cooldown_between_sessions_minutes: 30,
};
const orgId = '44444444-4444-4444-8444-444444444444';
const scriptId = '55555555-5555-4555-8555-555555555555';
const versionId = '66666666-6666-4666-8666-666666666666';
const published = {
  id: scriptId, org_id: orgId, name: 'Registration job', description: null, is_archived: false,
  created_at: first.created_at, updated_at: first.updated_at, current_version_id: versionId, node_count: 2,
  current_version: { id: versionId, script_id: scriptId, version: 1, dag_hash: 'a'.repeat(64), created_at: first.created_at },
};

beforeEach(() => {
  jest.resetAllMocks();
  grants.clear();
  for (const permission of ['device:read', 'device:write', 'account:read', 'pipeline:read', 'pipeline:write', 'script:read']) grants.add(permission);
  useAuthStore.setState({ user: { id: 'actor', email: 'fixture@example.test', org_id: orgId, role: 'org_owner' } });
});
afterEach(() => { useAuthStore.setState({ user: null }); });

function setupApi(getResource: () => object) {
  jest.mocked(api.get).mockImplementation(async path => {
    switch (path) {
      case '/application-profiles': return { data: { items: [first, second, builtin], total: 3 } };
      case '/scripts/catalog': return { data: { catalog_schema: 1, items: [published, { ...published, id: '77777777-7777-4777-8777-777777777777', name: 'Draft job', current_version_id: null, current_version: null, node_count: null }], total: 2, page: 1, per_page: 50, pages: 1 } };
      case bindingPath:
      case policyPath: return { data: getResource() };
      default: throw new Error(`Unexpected GET ${path}`);
    }
  });
}

async function openBinding() {
  render(<DeviceApplicationBinding deviceId="device-1" name="Fixture" onClose={jest.fn()} />, { wrapper: createWrapper() });
  await screen.findByRole('option', { name: 'Second Game · second-game' });
  return screen.getByRole('combobox', { name: 'Профиль приложения' });
}

async function openPolicy() {
  render(<ProfileAutomationSettings />, { wrapper: createWrapper() });
  fireEvent.click(screen.getByRole('button', { name: 'Автоматизация по приложениям' }));
  await screen.findByRole('option', { name: 'First Game · first-game' });
  fireEvent.change(screen.getByRole('combobox', { name: 'Профиль приложения' }), { target: { value: first.id } });
  return screen.findByRole('combobox', { name: 'Сценарий регистрации' });
}

it('resets the server on profile switch and confirms the exact device binding on a fresh GET', async () => {
  let observed = emptyBinding as typeof emptyBinding | typeof selectedBinding;
  setupApi(() => observed);
  jest.mocked(api.put).mockImplementation(async () => { observed = selectedBinding; return { data: selectedBinding }; });
  const profile = await openBinding();
  expect(within(profile).queryByRole('option', { name: /Black Russia/ })).not.toBeInTheDocument();
  fireEvent.change(profile, { target: { value: first.id } });
  fireEvent.change(screen.getByRole('combobox', { name: 'Сервер приложения' }), { target: { value: 'north' } });
  fireEvent.change(profile, { target: { value: second.id } });
  const server = screen.getByRole('combobox', { name: 'Сервер приложения' });
  const save = screen.getByRole('button', { name: 'Сохранить привязку' });
  expect(server).toHaveValue('');
  expect(within(server).queryByRole('option', { name: /North/ })).not.toBeInTheDocument();
  expect(save).toBeDisabled();
  fireEvent.change(server, { target: { value: 'south' } });
  fireEvent.click(save);
  expect(await screen.findByText('Привязка подтверждена повторным чтением.')).toBeInTheDocument();
  expect(api.put).toHaveBeenCalledWith(bindingPath, { application_profile_id: second.id, application_server_key: 'south', expected_revision: 0 });
  expect(jest.mocked(api.get).mock.calls.filter(([path]) => path === bindingPath)).toHaveLength(2);
});

it('requires reread after a stale binding conflict and clears both fields explicitly', async () => {
  let observed = selectedBinding as typeof selectedBinding | typeof emptyBinding;
  setupApi(() => observed);
  jest.mocked(api.put).mockRejectedValueOnce({ response: { status: 409, data: { detail: 'Application binding changed; reload before saving' } } });
  const profile = await openBinding();
  fireEvent.change(profile, { target: { value: '' } });
  const save = screen.getByRole('button', { name: 'Сохранить привязку' });
  fireEvent.click(save);
  expect(await screen.findByRole('alert')).toHaveTextContent('Привязка изменилась');
  expect(save).toBeDisabled();
  expect(api.put).toHaveBeenCalledTimes(1);
  observed = { ...selectedBinding, revision: 2 };
  fireEvent.click(screen.getByRole('button', { name: 'Перечитать привязку' }));
  await waitFor(() => expect(profile).toHaveValue(second.id));
  jest.mocked(api.put).mockImplementationOnce(async () => { observed = { ...emptyBinding, revision: 3 }; return { data: observed }; });
  fireEvent.change(profile, { target: { value: '' } });
  fireEvent.click(save);
  expect(await screen.findByText('Привязка подтверждена повторным чтением.')).toBeInTheDocument();
  expect(api.put).toHaveBeenLastCalledWith(bindingPath, { application_profile_id: null, application_server_key: null, expected_revision: 2 });
});

it('shows saved device binding to a viewer without allowing writes', async () => {
  grants.delete('device:write');
  setupApi(() => selectedBinding);
  const profile = await openBinding();
  expect(profile).toBeDisabled();
  expect(screen.getByRole('combobox', { name: 'Сервер приложения' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Сохранить привязку' })).toBeDisabled();
  expect(screen.getByText('Сохранено Second Game · South.')).toBeInTheDocument();
  expect(api.put).not.toHaveBeenCalled();
  expect(applicationBindingLabel({ server_name: 'Legacy' })).toBe('Legacy');
  expect(applicationBindingLabel({ ...selectedBinding, server_name: 'Legacy' }, [{ ...second, servers: [...second.servers], aliases: [] }])).toBe('Second Game · South');
});

it('saves only profile policy changes, validates numeric bounds and atomically clears an enabled mode', async () => {
  let observed: Record<string, unknown> = emptyPolicy;
  setupApi(() => observed);
  jest.mocked(api.put).mockImplementation(async (_path, body) => {
    const { expected_revision, ...changes } = body as { expected_revision: number };
    observed = { ...observed, ...changes, revision: expected_revision + 1 };
    return { data: observed };
  });
  const script = await openPolicy();
  await within(script).findByRole('option', { name: /Registration job/ });
  expect(within(script).queryByRole('option', { name: /Draft job/ })).not.toBeInTheDocument();
  fireEvent.change(script, { target: { value: published.id } });
  const enable = screen.getByRole('checkbox', { name: 'Включить регистрацию' });
  fireEvent.click(enable);
  const save = screen.getByRole('button', { name: 'Сохранить настройки профиля' });
  const timeout = screen.getByLabelText('Тайм-аут регистрации, с');
  fireEvent.change(timeout, { target: { value: '59' } });
  expect(save).toBeDisabled();
  fireEvent.change(timeout, { target: { value: '900' } });
  fireEvent.click(save);
  expect(await screen.findByText('Настройки профиля подтверждены повторным чтением.')).toBeInTheDocument();
  expect(api.put).toHaveBeenLastCalledWith(policyPath, { expected_revision: 0, registration_enabled: true, registration_script_id: published.id, registration_timeout_seconds: 900 });
  fireEvent.change(script, { target: { value: '' } });
  expect(enable).not.toBeChecked();
  fireEvent.click(save);
  expect(await screen.findByText('Сохранённая версия 2. Регистрация выключена, фарм выключен.')).toBeInTheDocument();
  expect(api.put).toHaveBeenLastCalledWith(policyPath, { expected_revision: 1, registration_enabled: false, registration_script_id: null });
});

it('does not confirm a policy whose follow-up read disagrees with the PUT receipt', async () => {
  setupApi(() => emptyPolicy);
  jest.mocked(api.put).mockResolvedValue({ data: { ...emptyPolicy, revision: 1, farming_script_id: published.id } });
  await openPolicy();
  const script = screen.getByRole('combobox', { name: 'Сценарий фарма' });
  await within(script).findByRole('option', { name: /Registration job/ });
  fireEvent.change(script, { target: { value: published.id } });
  const save = screen.getByRole('button', { name: 'Сохранить настройки профиля' });
  fireEvent.click(save);
  expect(await screen.findByRole('alert')).toHaveTextContent('Результат записи не подтверждён');
  expect(screen.queryByText('Настройки профиля подтверждены повторным чтением.')).not.toBeInTheDocument();
  expect(save).toBeDisabled();
  expect(api.put).toHaveBeenCalledTimes(1);
});
