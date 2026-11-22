import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AccountsPage from '@/app/(dashboard)/accounts/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { createWrapper } from '../helpers';

const mockQuery = jest.fn();
const mockRefetch = jest.fn();
let mockReadError = false;
let mockAccounts: Array<Record<string, unknown>> = [];
jest.mock('@/lib/hooks/useGameAccounts', () => ({
  ...jest.requireActual('@/lib/hooks/useGameAccounts'),
  useGameAccounts: (params: unknown) => {
    mockQuery(params);
    return { data: { items: mockAccounts, total: 150, pages: 3 }, isLoading: false, isError: mockReadError, isFetching: false, refetch: mockRefetch };
  },
  useAccountStats: () => ({ data: undefined }),
  useServers: () => ({ data: { servers: [] } }),
}));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn() } }));
jest.mock('@/components/sphere/DeviceSearchSelect', () => ({ DeviceSearchSelect: ({ onChange, disabled }: { onChange: (id: string) => void; disabled: boolean }) =>
  <button type="button" disabled={disabled} onClick={() => onChange('fixture-device')}>Выбрать устройство Fixture</button> }));
let mockCanWrite = false;
jest.mock('@/src/features/access/Capabilities', () => ({ useCapabilities: () => ({ can: () => mockCanWrite }) }));

beforeEach(() => {
  jest.resetAllMocks(); mockReadError = false; mockAccounts = []; mockCanWrite = false;
  useAuthStore.setState({ user: null });
  jest.mocked(api.post).mockResolvedValue({ data: {} } as never);
});
afterEach(() => { useAuthStore.setState({ user: null }); });

async function createDialog() {
  render(<AccountsPage />, { wrapper: createWrapper() });
  await userEvent.click(screen.getByRole('button', { name: 'Создать' }));
  fireEvent.change(screen.getByLabelText('Логин *'), { target: { value: 'Audit_User' } });
  fireEvent.change(screen.getByLabelText('Пароль игрового аккаунта'), { target: { value: 'test-only-password' } });
  return within(screen.getByRole('dialog')).getByRole('button', { name: 'Создать' });
}

it.each([0, 100, 65])('preserves lawfulness %s in the actual create POST', async (value) => {
  const submit = await createDialog();
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Законопослушность' }), { target: { value: String(value) } });
  await userEvent.click(submit);
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/game-accounts', expect.objectContaining({ lawfulness: value })));
});

it('omits an unset lawfulness rather than inventing the placeholder value', async () => {
  const submit = await createDialog();
  await userEvent.click(submit);
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(jest.mocked(api.post).mock.calls[0][1]).not.toHaveProperty('lawfulness');
});

it.each(['-1', '101', '3.5'])('blocks invalid lawfulness %s without sending a truncated number', async (value) => {
  const submit = await createDialog();
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Законопослушность' }), { target: { value } });
  expect(screen.getByRole('alert')).toHaveTextContent('Введите целое число от 0 до 100');
  expect(submit).toBeDisabled();
  fireEvent.click(submit);
  expect(api.post).not.toHaveBeenCalled();
});

it('applies only the final fast search after a full debounce delay and resets the page', () => {
  jest.useFakeTimers();
  try {
    const { unmount } = render(<AccountsPage />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByRole('button', { name: 'Следующая страница аккаунтов' }));
    expect(mockQuery).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
    const input = screen.getByPlaceholderText('Поиск по нику, логину...');
    fireEvent.change(input, { target: { value: 'a' } });
    act(() => { jest.advanceTimersByTime(100); });
    fireEvent.change(input, { target: { value: 'ab' } });
    act(() => { jest.advanceTimersByTime(100); });
    fireEvent.change(input, { target: { value: 'abc' } });
    act(() => { jest.advanceTimersByTime(299); });
    expect(mockQuery.mock.calls.some(([params]) => params.search)).toBe(false);
    act(() => { jest.advanceTimersByTime(1); });
    expect(mockQuery).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'abc', page: 1 }));
    expect(mockQuery.mock.calls.some(([params]) => params.search === 'a' || params.search === 'ab')).toBe(false);
    fireEvent.change(input, { target: { value: 'pending' } });
    const calls = mockQuery.mock.calls.length;
    unmount();
    act(() => { jest.advanceTimersByTime(300); });
    expect(mockQuery).toHaveBeenCalledTimes(calls);
  } finally { jest.useRealTimers(); }
});

it('distinguishes a catalog failure from an empty result and exposes recovery', () => {
  mockReadError = true;
  render(<AccountsPage />, { wrapper: createWrapper() });
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить аккаунты');
  expect(screen.queryByText('Нет аккаунтов. Создайте первый!')).not.toBeInTheDocument();
  expect(screen.getByText(/число записей не подтверждено/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку аккаунтов' }));
  expect(mockRefetch).toHaveBeenCalledTimes(1);
});

const revision = '2026-11-14T01:02:03.123456Z';
const appProfile = { id: 'app-profile-1', key: 'second-game', name: 'Second Game', android_package: 'dev.fixture.game',
  source: 'tenant', aliases: [], created_at: revision, updated_at: revision,
  servers: [{ key: 'east', name: 'East Server', domain: 'east.example.test', port: 1234 }] };
const builtinProfile = { id: 'app-builtin', key: 'black-russia', name: 'Black Russia', android_package: 'com.br.top',
  source: 'builtin', aliases: ['com.br.top', 'black_russia'], created_at: null, updated_at: null,
  servers: [{ key: 'red', name: 'RED', domain: 'red.example.test', port: 7777 }] };

function useCatalog(writable = true) {
  mockCanWrite = writable;
  useAuthStore.setState({ user: { id: 'actor', email: 'fixture@example.test', org_id: 'fixture-org', role: 'org_owner' } });
  jest.mocked(api.get).mockResolvedValue({ data: { items: [builtinProfile, appProfile], total: 2 } });
}

it('writes exact selected application key and only offers that application’s servers', async () => {
  useCatalog();
  const submit = await createDialog();
  const application = screen.getByLabelText('Приложение *');
  await screen.findByRole('option', { name: 'Second Game · second-game' });
  const server = screen.getByLabelText('Игровой сервер');
  fireEvent.change(server, { target: { value: 'RED' } });
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Законопослушность' }), { target: { value: '3.5' } });
  fireEvent.change(application, { target: { value: 'second-game' } });
  expect(server).toHaveValue('');
  expect(within(server).queryByRole('option', { name: 'RED' })).not.toBeInTheDocument();
  expect(screen.queryByRole('spinbutton', { name: 'Законопослушность' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Логин *'), { target: { value: 'generic+account@example.test' } });
  fireEvent.change(server, { target: { value: 'East Server' } });
  await userEvent.click(submit);
  expect(api.post).toHaveBeenCalledWith('/game-accounts', expect.objectContaining({ game: 'second-game', server_name: 'East Server', login: 'generic+account@example.test' }));
  const body = jest.mocked(api.post).mock.calls[0][1];
  expect(body).not.toHaveProperty('nickname');
  expect(body).not.toHaveProperty('gender');
  expect(body).not.toHaveProperty('lawfulness');
});

it('preserves a readable historical game/server when it is absent from the catalog', async () => {
  useCatalog();
  mockAccounts = [{ id: 'legacy', login: 'legacy-login', game: 'Historical App 2007', server_name: 'Old World', status: 'free', meta: {},
    created_at: revision }];
  render(<AccountsPage />, { wrapper: createWrapper() });
  expect(screen.getByText('Historical App 2007')).toBeInTheDocument();
  expect(screen.getByText('Old World')).toBeInTheDocument();
  await userEvent.click(screen.getByTitle('Редактировать'));
  const server = screen.getByLabelText('Игровой сервер');
  expect(server).toHaveValue('Old World');
  expect(within(server).getByRole('option', { name: 'Old World · сохранённое значение' })).toBeInTheDocument();
});

it('keeps account assignment open and describes a device application or server mismatch', async () => {
  useCatalog();
  mockAccounts = [{ id: 'account-1', login: 'fixture-login', game: appProfile.key, server_name: 'East Server', status: 'free', meta: {},
    created_at: revision }];
  jest.mocked(api.post).mockRejectedValueOnce({ response: { status: 409, data: { detail: 'Account does not match the device application and server' } } });
  render(<AccountsPage />, { wrapper: createWrapper() });
  await userEvent.click(screen.getByTitle('Назначить'));
  const dialog = within(screen.getByRole('dialog', { name: 'Назначить на устройство' }));
  expect(await dialog.findByText(/Second Game.*East Server/)).toBeInTheDocument();
  await userEvent.click(dialog.getByRole('button', { name: 'Выбрать устройство Fixture' }));
  await userEvent.click(dialog.getByRole('button', { name: 'Назначить' }));
  expect(await dialog.findByRole('alert')).toHaveTextContent('Приложение или сервер аккаунта не совпадает с привязкой устройства.');
  expect(api.post).toHaveBeenCalledWith('/game-accounts/account-1/assign', { device_id: 'fixture-device' });
});

it('filters exact historical game values including aliases and the old sentinel', async () => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
  useCatalog();
  mockAccounts = ['black_russia', 'com.br.top', '__all__'].map((game, index) => ({ id: `fixture-${index}`, game, login: `account-${index}`,
    server_name: null, status: 'free', meta: {}, created_at: revision }));
  render(<AccountsPage />, { wrapper: createWrapper() });
  const filter = screen.getByRole('combobox', { name: 'Фильтр по приложению' });
  fireEvent.keyDown(filter, { key: 'Enter' });
  fireEvent.click(await screen.findByRole('option', { name: 'Black Russia · black_russia' }));
  expect(mockQuery).toHaveBeenLastCalledWith(expect.objectContaining({ game: 'black_russia' }));
  fireEvent.keyDown(filter, { key: 'Enter' });
  fireEvent.click(await screen.findByRole('option', { name: '__all__' }));
  expect(mockQuery).toHaveBeenLastCalledWith(expect.objectContaining({ game: '__all__' }));
});

it('lets a viewer inspect the catalog and sends a revision-checked PATCH only for an editable profile', async () => {
  useCatalog(false);
  const view = render(<AccountsPage />, { wrapper: createWrapper() });
  await userEvent.click(screen.getByRole('button', { name: 'Приложения и серверы' }));
  const heading = await screen.findByText('Second Game · second-game · 1 серверов');
  fireEvent.click(heading);
  expect(screen.queryByRole('button', { name: 'Добавить приложение' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Изменить Second Game' })).not.toBeInTheDocument();
  mockCanWrite = true;
  view.rerender(<AccountsPage />);
  fireEvent.click(await screen.findByText('Изменить Second Game'));
  expect(screen.getByLabelText('Ключ сервера')).toHaveAttribute('readonly');
  expect(screen.getByLabelText('Название сервера')).toHaveAttribute('readonly');
  fireEvent.change(screen.getByLabelText('Порт'), { target: { value: '2345' } });
  jest.mocked(api.patch).mockResolvedValue({ status: 200, data: { ...appProfile, servers: [{ ...appProfile.servers[0], port: 2345 }] } });
  await userEvent.click(screen.getByRole('button', { name: 'Сохранить приложение' }));
  expect(api.patch).toHaveBeenCalledWith('/application-profiles/app-profile-1', expect.objectContaining({
    expected_updated_at: revision, servers: [{ ...appProfile.servers[0], port: 2345 }],
  }));
  expect(await screen.findByText('Сохранено приложение «Second Game».')).toBeInTheDocument();
});

it('creates a profile with a bounded server definition and blocks retry after an uncertain save', async () => {
  useCatalog();
  render(<AccountsPage />, { wrapper: createWrapper() });
  await userEvent.click(screen.getByRole('button', { name: 'Приложения и серверы' }));
  await userEvent.click(await screen.findByRole('button', { name: 'Добавить приложение' }));
  fireEvent.change(screen.getByLabelText('Ключ приложения'), { target: { value: 'third-game' } });
  fireEvent.change(screen.getByLabelText('Название приложения'), { target: { value: 'Third Game' } });
  await userEvent.click(screen.getByRole('button', { name: 'Добавить сервер' }));
  fireEvent.change(screen.getByLabelText('Ключ сервера'), { target: { value: 'west' } });
  fireEvent.change(screen.getByLabelText('Название сервера'), { target: { value: 'West Server' } });
  fireEvent.change(screen.getByLabelText('Домен'), { target: { value: 'west.example.test' } });
  fireEvent.change(screen.getByLabelText('Порт'), { target: { value: '1234' } });
  jest.mocked(api.post).mockRejectedValueOnce(new Error('fixture timeout'));
  const save = screen.getByRole('button', { name: 'Сохранить приложение' });
  await userEvent.click(save);
  expect(api.post).toHaveBeenCalledWith('/application-profiles', { key: 'third-game', name: 'Third Game', android_package: null,
    servers: [{ key: 'west', name: 'West Server', domain: 'west.example.test', port: 1234 }] });
  expect(await screen.findByRole('alert')).toHaveTextContent('Исход сохранения не подтверждён');
  expect(save).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Перечитать каталог' })).toBeEnabled();
  expect(api.post).toHaveBeenCalledTimes(1);
});
