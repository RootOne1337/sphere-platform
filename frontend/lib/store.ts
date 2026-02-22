'use client';
import { create } from 'zustand';
import { useState, useEffect } from 'react';
import { api } from './api';

interface AuthState {
  accessToken: string | null;
  user: { id: string; email: string; role: string; org_id: string } | null;

  setAccessToken: (token: string) => void;
  setUser: (user: AuthState['user']) => void;
  logout: () => void;
}

// Access token — ТОЛЬКО в памяти (Zustand без persist)
// Refresh token — ТОЛЬКО в HTTPOnly cookie (управляется сервером)
export const useAuthStore = create<AuthState>()((set) => ({
  accessToken: null,
  user: null,

  setAccessToken: (token) => set({ accessToken: token }),
  setUser: (user) => set({ user }),
  logout: () => set({ accessToken: null, user: null }),
}));

// ─── FIX 10.4: SILENT REFRESH ПРИ F5 ─────────────────────────────
// При перезагрузке страницы: POST /auth/refresh (httpOnly cookie идёт автоматически)
// 200 → сохраняем новый accessToken → пользователь залогинен
// 401 → cookie протухла → пользователь не залогинен (redirect в middleware)
// ──────────────────────────────────────────────────────────────────
export function useInitAuth(): boolean {
  const setAccessToken = useAuthStore((s) => s.setAccessToken);
  const setUser = useAuthStore((s) => s.setUser);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    api.post('/auth/refresh', {}, { withCredentials: true })
      .then((res) => {
        setAccessToken(res.data.access_token);
        if (res.data.user) setUser(res.data.user);
      })
      .catch(() => {
        // refreshToken протух или отсутствует — пользователь не залогинен
      })
      .finally(() => setReady(true));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return ready;
}
