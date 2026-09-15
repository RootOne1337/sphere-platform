import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '@/lib/store';

const mockReplace = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ replace: mockReplace }) }));
// Capture the real dedicated login client, then use its transport adapter (no HTTP listener).
const create = jest.spyOn(axios, 'create');
const LoginPage = require('@/app/(auth)/login/page').default;
const loginApi = create.mock.results[0].value as AxiosInstance;
create.mockRestore();

let finish: (data: unknown) => void;
let requests: InternalAxiosRequestConfig[];
beforeEach(() => {
  useAuthStore.getState().logout();
  localStorage.clear();
  mockReplace.mockClear();
  requests = [];
  loginApi.defaults.adapter = async config => {
    requests.push(config);
    const data = await new Promise(resolve => { finish = resolve; });
    return { config, data, status: 200, statusText: 'OK', headers: {} };
  };
});
function submit() {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'audit@example.test' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'audit-fixture-password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
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

it('applies a valid login atomically and navigates without another token rotation', async () => {
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
  expect(mockReplace).toHaveBeenCalledWith('/dashboard');
});

it('applies the MFA result to the matching login attempt', async () => {
  render(<LoginPage />);
  submit();
  await waitFor(() => expect(requests).toHaveLength(1));
  await act(async () => finish({ mfa_required: true, state_token: 'mfa-a' }));
  fireEvent.change(screen.getByLabelText('TOTP Code'), { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[1].url).toBe('/auth/login/mfa');
  await act(async () => finish(tokens));
  expect(useAuthStore.getState().accessToken).toBe('access-a');
  expect(mockReplace).toHaveBeenCalledWith('/dashboard');
});

it('ignores MFA completion after returning to the login form', async () => {
  render(<LoginPage />);
  submit();
  await waitFor(() => expect(requests).toHaveLength(1));
  await act(async () => finish({ mfa_required: true, state_token: 'mfa-a' }));
  fireEvent.change(screen.getByLabelText('TOTP Code'), { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
  await waitFor(() => expect(requests).toHaveLength(2));
  fireEvent.click(screen.getByRole('button', { name: 'Back to login' }));
  await act(async () => finish(tokens));
  expect(useAuthStore.getState().accessToken).toBeNull();
  expect(mockReplace).not.toHaveBeenCalled();
});

it('displays a server revocation warning on the login page', () => {
  useAuthStore.setState({ logoutWarning: 'Server session revocation could not be confirmed.' });
  render(<LoginPage />);
  expect(screen.getByRole('status')).toHaveTextContent('could not be confirmed');
});
