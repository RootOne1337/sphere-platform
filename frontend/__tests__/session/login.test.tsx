import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '@/lib/store';
import { clearReturnDestination, readReturnDestination } from '@/src/features/access/returnDestination';

const mockReplace = jest.fn();
let mockPath = '/login';
jest.mock('next/navigation', () => ({ usePathname: () => mockPath, useRouter: () => ({ replace: mockReplace }) }));
// Capture the real dedicated login client, then use its transport adapter (no HTTP listener).
const create = jest.spyOn(axios, 'create');
const LoginPage = require('@/app/(auth)/login/page').default;
const loginApi = create.mock.results[0].value as AxiosInstance;
create.mockRestore();
const { Providers } = require('@/app/providers');
const { api } = require('@/lib/api') as typeof import('@/lib/api');
const apiAdapter = api.defaults.adapter;

let finish: (data: unknown) => void;
let requests: InternalAxiosRequestConfig[];
beforeEach(() => {
  useAuthStore.getState().logout();
  localStorage.clear();
  clearReturnDestination();
  mockPath = '/login';
  mockReplace.mockClear();
  requests = [];
  loginApi.defaults.adapter = async config => {
    requests.push(config);
    const data = await new Promise(resolve => { finish = resolve; });
    return { config, data, status: 200, statusText: 'OK', headers: {} };
  };
});
afterEach(() => { api.defaults.adapter = apiAdapter; });
function submit() {
  fireEvent.change(screen.getByLabelText('Электронная почта'), { target: { value: 'audit@example.test' } });
  fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'audit-fixture-password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Войти в Sphere' }));
}
const tokens = { access_token: 'access-a', refresh_token: 'refresh-a',
  user: { id: 'a', org_id: 'a', role: 'admin', email: 'audit@example.test' } };

it('ignores login completion after logout invalidates the attempt', async () => {
  render(<LoginPage />);
  submit();
  await waitFor(() => expect(requests).toHaveLength(1));
  act(() => useAuthStore.getState().logout());
  await act(async () => finish(tokens));
  expect(useAuthStore.getState().accessToken).toBeNull();
  expect(mockReplace).not.toHaveBeenCalled();
});

it('applies a valid login atomically and leaves navigation to the capability guard', async () => {
  render(<LoginPage />);
  submit();
  await waitFor(() => expect(requests).toHaveLength(1));
  const partialStates: unknown[] = [];
  const unsubscribe = useAuthStore.subscribe(state => {
    if (Boolean(state.accessToken) !== Boolean(state.user)) partialStates.push(state);
  });
  await act(async () => finish(tokens));
  unsubscribe();
  expect(partialStates).toHaveLength(0);
  expect(useAuthStore.getState().user).toEqual(tokens.user);
  expect(mockReplace).not.toHaveBeenCalled();
});

it('applies the MFA result to the matching login attempt', async () => {
  render(<LoginPage />);
  submit();
  await waitFor(() => expect(requests).toHaveLength(1));
  await act(async () => finish({ mfa_required: true, state_token: 'mfa-a' }));
  fireEvent.change(screen.getByLabelText('Код подтверждения'), { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить вход' }));
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[1].url).toBe('/auth/login/mfa');
  await act(async () => finish(tokens));
  expect(useAuthStore.getState().accessToken).toBe('access-a');
  expect(mockReplace).not.toHaveBeenCalled();
});

it('ignores MFA completion after returning to the login form', async () => {
  render(<LoginPage />);
  submit();
  await waitFor(() => expect(requests).toHaveLength(1));
  await act(async () => finish({ mfa_required: true, state_token: 'mfa-a' }));
  fireEvent.change(screen.getByLabelText('Код подтверждения'), { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить вход' }));
  await waitFor(() => expect(requests).toHaveLength(2));
  fireEvent.click(screen.getByRole('button', { name: 'Вернуться ко входу' }));
  await act(async () => finish(tokens));
  expect(useAuthStore.getState().accessToken).toBeNull();
  expect(mockReplace).not.toHaveBeenCalled();
});

it.each([false, true])('returns from a guarded deep link after password/MFA=%s and checks capabilities first', async mfa => {
  mockPath = '/tasks/fixture-task';
  window.history.replaceState({}, '', `${mockPath}?tab=logs`);
  let releasePermissions!: () => void;
  const capabilityChecks = jest.fn();
  api.defaults.adapter = async config => {
    capabilityChecks(config.url);
    await new Promise<void>(resolve => { releasePermissions = resolve; });
    return { config, status: 200, statusText: 'OK', headers: {}, data: {
      schema_version: 1, user_id: tokens.user.id, org_id: tokens.user.org_id, role: tokens.user.role, permissions: ['script:read'],
    } };
  };
  const view = render(<Providers><div>private task</div></Providers>);
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/login'));
  expect(screen.queryByText('private task')).not.toBeInTheDocument();
  mockPath = '/login';
  window.history.replaceState({}, '', mockPath);
  view.rerender(<Providers><LoginPage /></Providers>);
  submit();
  await waitFor(() => expect(requests).toHaveLength(1));
  if (mfa) {
    await act(async () => finish({ mfa_required: true, state_token: 'fixture-mfa' }));
    fireEvent.change(screen.getByLabelText('Код подтверждения'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить вход' }));
    await waitFor(() => expect(requests).toHaveLength(2));
  }
  await act(async () => finish(tokens));
  await waitFor(() => expect(capabilityChecks).toHaveBeenCalledWith('/auth/capabilities'));
  expect(mockReplace).toHaveBeenCalledTimes(1);
  expect(readReturnDestination()).toBe('/tasks/fixture-task?tab=logs');
  await act(async () => releasePermissions());
  await waitFor(() => expect(mockReplace).toHaveBeenLastCalledWith('/tasks/fixture-task?tab=logs'));
  expect(readReturnDestination()).toBeNull();
});

it('displays a server revocation warning on the login page', () => {
  useAuthStore.setState({ logoutWarning: 'Server session revocation could not be confirmed.' });
  render(<LoginPage />);
  expect(screen.getByRole('status')).toHaveTextContent('could not be confirmed');
});

it('can reveal and conceal the password without submitting or clearing it', () => {
  render(<LoginPage />);
  const password = screen.getByLabelText('Пароль');
  fireEvent.change(password, { target: { value: 'kept-value' } });
  fireEvent.click(screen.getByRole('button', { name: 'Показать пароль' }));
  expect(password).toHaveAttribute('type', 'text');
  expect(password).toHaveValue('kept-value');
  fireEvent.click(screen.getByRole('button', { name: 'Скрыть пароль' }));
  expect(password).toHaveAttribute('type', 'password');
  expect(requests).toHaveLength(0);
});
