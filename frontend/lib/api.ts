import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { assertSession, refreshSession, useAuthStore } from './store';

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? '/api/v1',
  timeout: 5000,
  withCredentials: true,
});

type SessionRequest = InternalAxiosRequestConfig & { _sessionVersion?: number; _retry?: boolean };

api.interceptors.request.use((config: SessionRequest) => {
  const state = useAuthStore.getState();
  config._sessionVersion ??= state.sessionVersion;
  assertSession(config._sessionVersion);
  if (state.accessToken) config.headers.Authorization = `Bearer ${state.accessToken}`;
  else delete config.headers.Authorization;
  return config;
});

api.interceptors.response.use(
  response => {
    assertSession((response.config as SessionRequest)._sessionVersion!);
    return response;
  },
  async (error: AxiosError) => {
    const original = error.config as SessionRequest | undefined;
    if (!original) throw error;
    assertSession(original._sessionVersion!);
    if (error.response?.status !== 401 || original._retry || original.url?.includes('/auth/')) throw error;
    original._retry = true;
    const current = useAuthStore.getState().accessToken;
    // Another request may already have rotated this same session's token.
    if (!current || original.headers.Authorization === `Bearer ${current}`) {
      await refreshSession(original._sessionVersion);
    }
    assertSession(original._sessionVersion!);
    return api(original);
  },
);
