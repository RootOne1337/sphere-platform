// Run from frontend with the evidence directory as Jest root. No network.
const React = require('react');
const { render, screen, fireEvent, waitFor } = require('@testing-library/react');
const axios = require('axios').default;
const { QueryClient, QueryClientProvider } = require('@tanstack/react-query');
const { useAuthStore } = require('@/lib/store');

const mockReplace = jest.fn();
const mockRouter = { replace: mockReplace };
let mockPath = '/tasks/fixture-task';
jest.mock('next/navigation', () => ({ useRouter: () => mockRouter, usePathname: () => mockPath }));

const create = jest.spyOn(axios, 'create');
const LoginPage = require('@/app/(auth)/login/page').default;
const loginApi = create.mock.results.at(-1).value;
create.mockRestore();
const { Providers } = require('@/app/providers');
const { api } = require('@/lib/api');
const UsersPage = require('@/app/(dashboard)/users/page').default;
const defaultAdapter = api.defaults.adapter;
const refreshAdapter = axios.defaults.adapter;

const account = { id: 'api-fixture', org_id: 'org-fixture', email: 'operator@example.invalid', role: 'api_user' };
const session = { access_token: 'fixture', user: account };

function submitPassword() {
  fireEvent.change(screen.getByLabelText('Электронная почта'), { target: { value: account.email } });
  fireEvent.change(screen.getByLabelText('Пароль'), { target: { value: 'fixture-password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Войти в Sphere' }));
}

beforeEach(() => {
  useAuthStore.getState().logout();
  localStorage.clear();
  mockReplace.mockClear();
});
afterEach(() => {
  api.defaults.adapter = defaultAdapter;
  axios.defaults.adapter = refreshAdapter;
});

it('loses the incident destination before password login and lands on a fixed route', async () => {
  window.history.replaceState({}, '', '/tasks/fixture-task?tab=logs');
  const guarded = render(React.createElement(Providers, null, React.createElement('div', null, 'private content')));
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/login'));
  expect(screen.queryByText('private content')).toBeNull();
  guarded.unmount();
  loginApi.defaults.adapter = async config => ({ config, data: session, status: 200, headers: {} });
  render(React.createElement(LoginPage));
  submitPassword();
  await waitFor(() => expect(mockReplace).toHaveBeenLastCalledWith('/dashboard'));
});

it('also chooses a fixed destination after MFA', async () => {
  window.history.replaceState({}, '', '/login');
  loginApi.defaults.adapter = async config => ({ config, status: 200, headers: {}, data:
    config.url === '/auth/login' ? { mfa_required: true, state_token: 'mfa-fixture' } : session });
  render(React.createElement(LoginPage));
  submitPassword();
  const code = await screen.findByLabelText('Код подтверждения');
  fireEvent.change(code, { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить вход' }));
  await waitFor(() => expect(mockReplace).toHaveBeenLastCalledWith('/dashboard'));
});

it('routes a cold-session refresh outage to the same login as a confirmed rejection', async () => {
  const requests = [];
  useAuthStore.setState({ explicitlySignedOut: false });
  axios.defaults.adapter = async config => {
    requests.push(config.url);
    throw new axios.AxiosError('fixture temporary outage', 'ERR_BAD_RESPONSE', config, undefined, {
      config, status: 503, statusText: 'Unavailable', headers: {}, data: {},
    });
  };
  render(React.createElement(Providers, null, React.createElement('div', null, 'private content')));
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/login'));
  expect(requests).toEqual([`${process.env.NEXT_PUBLIC_API_URL ?? '/api/v1'}/auth/refresh`]);
  expect(useAuthStore.getState().explicitlySignedOut).toBe(false);
  expect(screen.queryByText('private content')).toBeNull();
});

it('labels users from two organizations as a single organization', async () => {
  useAuthStore.setState({ accessToken: 'fixture', user: { ...account, role: 'super_admin' } });
  const makeUser = (id, org_id) => ({ id, org_id, email: `${id}@example.invalid`, role: 'viewer',
    is_active: true, mfa_enabled: false, created_at: '2026-11-14T00:00:00Z', last_login_at: null });
  const first = makeUser('first-fixture', 'first-org-fixture');
  const second = makeUser('second-fixture', 'second-org-fixture');
  api.defaults.adapter = async config => ({ config, status: 200, headers: {},
    data: { items: [first, second], total: 2, page: 1, per_page: 50, pages: 1 } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(React.createElement(QueryClientProvider, { client }, React.createElement(UsersPage)));
  try {
    expect(await screen.findByText(first.email)).toBeVisible();
    expect(screen.getByText(second.email)).toBeVisible();
    expect(screen.getByText('Участники организации')).toBeVisible();
    expect(screen.queryByText(first.org_id)).toBeNull();
    expect(screen.queryByText(second.org_id)).toBeNull();
  } finally {
    view.unmount();
    client.clear();
  }
});
