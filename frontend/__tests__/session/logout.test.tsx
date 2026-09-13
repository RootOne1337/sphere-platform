import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import axios, { InternalAxiosRequestConfig } from 'axios';
import { NOCSidebar } from '@/src/features/navigation/NOCSidebar';
import { beginLogin, getRefreshToken, saveRefreshToken, signOut, useAuthStore, useInitAuth } from '@/lib/store';

const mockReplace = jest.fn();
jest.mock('next/navigation', () => ({
  usePathname: () => '/accounts',
  useRouter: () => ({ replace: mockReplace }),
}));
const originalAdapter = axios.defaults.adapter;
beforeEach(() => {
  localStorage.clear();
  mockReplace.mockClear();
  useAuthStore.getState().setAccessToken('access-a');
  useAuthStore.getState().setUser({ id: 'a', org_id: 'a', role: 'admin', email: 'audit@example.test' });
  saveRefreshToken('refresh-a');
});
afterEach(() => { axios.defaults.adapter = originalAdapter; });

it('Sign out immediately removes local credentials and revokes the captured server session', async () => {
  const requests: InternalAxiosRequestConfig[] = [];
  let finish!: () => void;
  axios.defaults.adapter = async config => {
    requests.push(config);
    await new Promise<void>(resolve => { finish = resolve; });
    return { config, data: '', status: 204, statusText: 'No Content', headers: {} };
  };
  render(<NOCSidebar />);
  fireEvent.click(screen.getByTitle('Sign out'));
  expect(useAuthStore.getState().accessToken).toBeNull();
  expect(getRefreshToken()).toBeNull();
  expect(mockReplace).toHaveBeenCalledWith('/login');
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0].url).toBe('/api/v1/auth/logout');
  expect(requests[0].headers.Authorization).toBe('Bearer access-a');
  expect(requests[0].headers['X-Refresh-Token']).toBe('refresh-a');
  expect(requests[0].withCredentials).toBe(true);
  expect(requests[0].timeout).toBeGreaterThan(0);
  finish();
});

it('keeps the browser signed out on network failure and reports unconfirmed revocation', async () => {
  axios.defaults.adapter = async () => { throw new Error('offline'); };
  expect(await signOut()).toBe(false);
  expect(useAuthStore.getState().user).toBeNull();
  expect(getRefreshToken()).toBeNull();
  expect(useAuthStore.getState().logoutWarning).toContain('could not be confirmed');
  const restored = renderHook(() => useInitAuth());
  await waitFor(() => expect(restored.result.current).toBe(true));
  expect(useAuthStore.getState().user).toBeNull();
});

it('does not let an old logout failure alter a subsequent login', async () => {
  let fail!: (error: Error) => void;
  axios.defaults.adapter = () => new Promise((_, reject) => { fail = reject; });
  const pending = signOut();
  const version = beginLogin();
  useAuthStore.getState().completeLogin({ access_token: 'access-b', refresh_token: 'refresh-b',
    user: { id: 'b', org_id: 'b', role: 'admin', email: 'audit@example.test' } }, version);
  fail(new Error('old connection failed'));
  expect(await pending).toBe(false);
  expect(useAuthStore.getState().accessToken).toBe('access-b');
  expect(getRefreshToken()).toBe('refresh-b');
  expect(useAuthStore.getState().logoutWarning).toBeNull();
});

it('still clears local access and uses the cookie when browser storage is unavailable', async () => {
  const requests: InternalAxiosRequestConfig[] = [];
  axios.defaults.adapter = async config => {
    requests.push(config);
    return { config, data: '', status: 204, statusText: 'No Content', headers: {} };
  };
  const denied = () => { throw new DOMException('Storage disabled', 'SecurityError'); };
  (localStorage.getItem as jest.Mock).mockImplementationOnce(denied);
  (localStorage.removeItem as jest.Mock).mockImplementationOnce(denied);
  (localStorage.setItem as jest.Mock).mockImplementationOnce(denied);
  await act(async () => expect(await signOut()).toBe(true));
  expect(useAuthStore.getState().accessToken).toBeNull();
  expect(requests[0].headers.Authorization).toBe('Bearer access-a');
  expect(requests[0].withCredentials).toBe(true);
  expect(requests[0].headers['X-Refresh-Token']).toBeUndefined();
  const restored = renderHook(() => useInitAuth());
  await waitFor(() => expect(restored.result.current).toBe(true));
  expect(requests).toHaveLength(1);
});
