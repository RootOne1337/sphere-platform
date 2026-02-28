import axios, { AxiosError } from 'axios';
import { useAuthStore } from './store';
import { getRefreshToken, saveRefreshToken, clearRefreshToken } from './store';

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL ?? '/api/v1',
  timeout: 5000,
  withCredentials: true,
});

// ⚠️ АВТОРИЗАЦИЯ ОТКЛЮЧЕНА НА ВРЕМЯ РАЗРАБОТКИ
const _DEV_SKIP_AUTH = process.env.NEXT_PUBLIC_DEV_SKIP_AUTH === 'true';

// Request: добавить Authorization
api.interceptors.request.use((config) => {
  if (_DEV_SKIP_AUTH) return config;
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response: refresh при 401 (отключен при DEV_SKIP_AUTH)
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (err: unknown) => void;
}> = [];

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    // DEV_SKIP_AUTH: не пытаемся refresh, не редиректим
    if (_DEV_SKIP_AUTH) return Promise.reject(error);

    const original = error.config as typeof error.config & { _retry?: boolean };

    // Не перехватывать 401 от auth endpoints (логин, refresh, logout)
    const isAuthEndpoint = original.url?.includes('/auth/');
    if (error.response?.status === 401 && !original._retry && !isAuthEndpoint) {
      if (isRefreshing) {
        // Ставим в очередь — ждём завершения текущего refresh
        return new Promise((resolve, reject) => {
          failedQueue.push({
            resolve: (token) => {
              original.headers!.Authorization = `Bearer ${token}`;
              resolve(api(original));
            },
            reject,
          });
        });
      }

      original._retry = true;
      isRefreshing = true;

      try {
        const storedRefresh = getRefreshToken();
        const headers: Record<string, string> = {};
        if (storedRefresh) {
          headers['X-Refresh-Token'] = storedRefresh;
        }

        // Refresh token отправляется через cookie + header (dual mode)
        const { data } = await axios.post(
          `${api.defaults.baseURL}/auth/refresh`,
          {},
          { withCredentials: true, headers },
        );

        const newAccess = data.access_token as string;
        useAuthStore.getState().setAccessToken(newAccess);

        // Сохраняем новый refresh_token (ротация)
        if (data.refresh_token) {
          saveRefreshToken(data.refresh_token);
        }

        failedQueue.forEach(({ resolve }) => resolve(newAccess));
        failedQueue = [];

        original.headers!.Authorization = `Bearer ${newAccess}`;
        return api(original);
      } catch (refreshError) {
        failedQueue.forEach(({ reject }) => reject(refreshError));
        failedQueue = [];
        useAuthStore.getState().logout();
        if (typeof window !== 'undefined') {
          window.location.href = '/login';
        }
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  },
);
