'use client';
import { create } from 'zustand';
import { useState, useEffect } from 'react';
import axios from 'axios';

// Ключ для хранения refresh_token в localStorage (fallback для сред без cookie — tunnel/proxy)
const REFRESH_TOKEN_KEY = 'sphere_refresh_token';

/** Сохранить refresh_token в localStorage */
export function saveRefreshToken(token: string) {
  if (typeof window !== 'undefined') {
    localStorage.setItem(REFRESH_TOKEN_KEY, token);
  }
}

/** Получить refresh_token из localStorage */
export function getRefreshToken(): string | null {
  if (typeof window !== 'undefined') {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  }
  return null;
}

/** Удалить refresh_token из localStorage */
export function clearRefreshToken() {
  if (typeof window !== 'undefined') {
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  }
}

interface AuthState {
  accessToken: string | null;
  user: { id: string; email: string; role: string; org_id: string; mfa_enabled?: boolean } | null;

  setAccessToken: (token: string) => void;
  setUser: (user: AuthState['user']) => void;
  logout: () => void;
}

// Access token — ТОЛЬКО в памяти (Zustand без persist)
export const useAuthStore = create<AuthState>()((set) => ({
  accessToken: null,
  user: null,

  setAccessToken: (token) => set({ accessToken: token }),
  setUser: (user) => set({ user }),
  logout: () => {
    clearRefreshToken();
    set({ accessToken: null, user: null });
  },
}));

// ─── SILENT REFRESH ПРИ F5 ───────────────────────────────────────
// При перезагрузке: отправляем refresh_token через header (localStorage fallback)
// 200 → сохраняем новый accessToken + refresh_token → пользователь залогинен
// 401 → токен протух → пользователь не залогинен
// ──────────────────────────────────────────────────────────────────
// ⚠️ АВТОРИЗАЦИЯ ОТКЛЮЧЕНА НА ВРЕМЯ РАЗРАБОТКИ
const _DEV_SKIP_AUTH = true;

export function useInitAuth(): boolean {
  const [ready, setReady] = useState(!_DEV_SKIP_AUTH ? false : true);

  useEffect(() => {
    // DEV_SKIP_AUTH: не делаем никаких запросов, сразу ready
    if (_DEV_SKIP_AUTH) return;

    const base = process.env.NEXT_PUBLIC_API_URL ?? '/api/v1';
    const storedRefresh = getRefreshToken();
    const setAccessToken = useAuthStore.getState().setAccessToken;
    const setUser = useAuthStore.getState().setUser;

    // Отправляем refresh_token и через cookie (withCredentials), и через header (fallback)
    const headers: Record<string, string> = {};
    if (storedRefresh) {
      headers['X-Refresh-Token'] = storedRefresh;
    }

    axios.post(`${base}/auth/refresh`, {}, { withCredentials: true, headers })
      .then((res) => {
        setAccessToken(res.data.access_token);
        if (res.data.user) setUser(res.data.user);
        // Сохраняем новый refresh_token (ротация)
        if (res.data.refresh_token) {
          saveRefreshToken(res.data.refresh_token);
        }
      })
      .catch(() => {
        // refreshToken протух или отсутствует — пользователь не залогинен
        clearRefreshToken();
      })
      .finally(() => setReady(true));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return ready;
}
