import { StrictMode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import axios, { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { api } from '@/lib/api';
import { getRefreshToken, saveRefreshToken, useAuthStore, useInitAuth } from '@/lib/store';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function tokens(org: string) {
  return { access_token: `access-${org}`, refresh_token: `refresh-${org}`,
    user: { id: `user-${org}`, org_id: org, email: 'audit@example.test', role: 'admin' } };
}
function identify(org: string) {
  const data = tokens(org);
  useAuthStore.getState().setAccessToken(data.access_token);
  useAuthStore.getState().setUser(data.user);
  saveRefreshToken(data.refresh_token);
}
function response(config: InternalAxiosRequestConfig, data: unknown, status = 200): AxiosResponse {
  return { config, data, status, statusText: String(status), headers: {} };
}
function unauthorized(config: InternalAxiosRequestConfig) {
  return new AxiosError('expired', 'ERR_BAD_REQUEST', config, undefined, response(config, {}, 401));
}

const defaultAdapter = axios.defaults.adapter;
const apiAdapter = api.defaults.adapter;
let refreshReply: ReturnType<typeof deferred<ReturnType<typeof tokens>>>;
let refreshRequests: InternalAxiosRequestConfig[];
beforeEach(() => {
  useAuthStore.getState().logout();
  localStorage.clear();
  refreshReply = deferred();
  refreshRequests = [];
  axios.defaults.adapter = async config => {
    if (!config.url?.endsWith('/auth/refresh')) throw new Error(`unexpected request ${config.url}`);
    refreshRequests.push(config);
    return response(config, await refreshReply.promise);
  };
});
afterEach(() => { axios.defaults.adapter = defaultAdapter; api.defaults.adapter = apiAdapter; });

it('does not resurrect a logged-out session from a delayed startup refresh', async () => {
  const hook = renderHook(() => useInitAuth());
  await waitFor(() => expect(refreshRequests).toHaveLength(1));
  act(() => useAuthStore.getState().logout());
  await act(async () => refreshReply.resolve(tokens('a')));
  await waitFor(() => expect(hook.result.current).toBe(true));
  expect(useAuthStore.getState().accessToken).toBeNull();
  expect(getRefreshToken()).toBeNull();
});

it('shares one startup refresh through StrictMode effect replay', async () => {
  const hook = renderHook(() => useInitAuth(), { wrapper: ({ children }) => <StrictMode>{children}</StrictMode> });
  await act(async () => refreshReply.resolve(tokens('a')));
  await waitFor(() => expect(hook.result.current).toBe(true));
  expect(refreshRequests).toHaveLength(1);
  expect(useAuthStore.getState().user?.org_id).toBe('a');
});

it('does not replay a mutation or restore credentials after logout during API refresh', async () => {
  identify('a');
  const requests: InternalAxiosRequestConfig[] = [];
  api.defaults.adapter = async config => {
    requests.push(config);
    if (requests.length === 1) throw unauthorized(config);
    return response(config, { changed: true });
  };
  const pending = api.post('/tasks/old-task/cancel').catch(error => error);
  await waitFor(() => expect(refreshRequests).toHaveLength(1));
  act(() => useAuthStore.getState().logout());
  refreshReply.resolve(tokens('a'));
  expect(await pending).toBeInstanceOf(Error);
  expect(requests).toHaveLength(1);
  expect(useAuthStore.getState().accessToken).toBeNull();
  expect(getRefreshToken()).toBeNull();
});

it('does not refresh or replay an old 401 under a newly signed-in tenant', async () => {
  identify('a');
  const first = deferred<void>();
  const requests: InternalAxiosRequestConfig[] = [];
  api.defaults.adapter = async config => {
    requests.push(config);
    if (requests.length === 1) { await first.promise; throw unauthorized(config); }
    return response(config, { changed: true });
  };
  const pending = api.post('/accounts', { label: 'belongs to A' }).catch(error => error);
  await waitFor(() => expect(requests).toHaveLength(1));
  identify('b');
  refreshReply.resolve(tokens('b'));
  first.resolve();
  expect(await pending).toBeInstanceOf(Error);
  expect(refreshRequests).toHaveLength(0);
  expect(requests).toHaveLength(1);
});

it('rejects a successful stale response after the active identity changes', async () => {
  identify('a');
  const oldReply = deferred<void>();
  const seen = jest.fn();
  api.defaults.adapter = async config => { seen(); await oldReply.promise; return response(config, 'tenant A credential'); };
  const pending = api.get('/accounts').catch(error => error);
  await waitFor(() => expect(seen).toHaveBeenCalledTimes(1));
  identify('b');
  oldReply.resolve();
  expect(await pending).toBeInstanceOf(Error);
});

it('ignores an old refresh failure after a different login succeeds', async () => {
  identify('a');
  api.defaults.adapter = async config => { throw unauthorized(config); };
  const pending = api.get('/devices').catch(error => error);
  await waitFor(() => expect(refreshRequests).toHaveLength(1));
  identify('b');
  refreshReply.reject(new Error('old refresh connection failed'));
  expect(await pending).toBeInstanceOf(Error);
  expect(useAuthStore.getState().accessToken).toBe('access-b');
  expect(getRefreshToken()).toBe('refresh-b');
});

it('coalesces concurrent 401s and retries each request at most once', async () => {
  identify('a');
  const requests: InternalAxiosRequestConfig[] = [];
  api.defaults.adapter = async config => {
    requests.push(config);
    if (config.headers.Authorization === 'Bearer access-a') throw unauthorized(config);
    return response(config, config.url);
  };
  const pending = Promise.all([api.get('/devices'), api.get('/accounts')]);
  await waitFor(() => expect(requests).toHaveLength(2));
  await waitFor(() => expect(refreshRequests).toHaveLength(1));
  refreshReply.resolve({ ...tokens('a'), access_token: 'rotated-a' });
  expect(await pending).toHaveLength(2);
  expect(refreshRequests).toHaveLength(1);
  expect(requests).toHaveLength(4);
});

it('bounds the refresh transport wait', async () => {
  const hook = renderHook(() => useInitAuth());
  await act(async () => refreshReply.resolve(tokens('a')));
  await waitFor(() => expect(hook.result.current).toBe(true));
  expect(refreshRequests[0].timeout).toBeGreaterThan(0);
  expect(refreshRequests[0].timeout).toBeLessThanOrEqual(10_000);
});

it('shares startup refresh with a second initializer and an API 401', async () => {
  const first = renderHook(() => useInitAuth());
  const second = renderHook(() => useInitAuth());
  api.defaults.adapter = async config => {
    if (!config.headers.Authorization) throw unauthorized(config);
    return response(config, 'accounts');
  };
  const pending = api.get('/accounts');
  await waitFor(() => expect(refreshRequests).toHaveLength(1));
  await act(async () => refreshReply.resolve(tokens('a')));
  expect((await pending).data).toBe('accounts');
  expect(first.result.current).toBe(true);
  expect(second.result.current).toBe(true);
  expect(refreshRequests).toHaveLength(1);
});

it('does not try a second refresh when both retried requests remain unauthorized', async () => {
  identify('a');
  let count = 0;
  api.defaults.adapter = async config => { count++; throw unauthorized(config); };
  const pending = Promise.allSettled([api.get('/devices'), api.get('/accounts')]);
  await waitFor(() => expect(count).toBe(2));
  await waitFor(() => expect(refreshRequests).toHaveLength(1));
  refreshReply.resolve({ ...tokens('a'), access_token: 'rotated-a' });
  expect((await pending).every(result => result.status === 'rejected')).toBe(true);
  expect(count).toBe(4);
  expect(refreshRequests).toHaveLength(1);
});

it('fails closed if the cookie refresh belongs to a different identity', async () => {
  identify('a');
  api.defaults.adapter = async config => { throw unauthorized(config); };
  const pending = api.get('/accounts').catch(error => error);
  await waitFor(() => expect(refreshRequests).toHaveLength(1));
  refreshReply.resolve(tokens('b'));
  expect(await pending).toBeInstanceOf(Error);
  expect(useAuthStore.getState().user).toBeNull();
  expect(getRefreshToken()).toBeNull();
});

it('does not restore a cookie session after an explicit logout and remount', async () => {
  useAuthStore.getState().logout();
  const hook = renderHook(() => useInitAuth());
  await waitFor(() => expect(hook.result.current).toBe(true));
  expect(refreshRequests).toHaveLength(0);
  expect(useAuthStore.getState().user).toBeNull();
});
