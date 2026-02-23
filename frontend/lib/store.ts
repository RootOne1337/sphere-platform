'use client';
import { create } from 'zustand';
import { useState, useEffect } from 'react';
import axios from 'axios';
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
    // Use raw axios (no interceptors) to avoid 401→refresh→redirect loop on startup
    const base = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1';
    axios.post(`${base}/auth/refresh`, {}, { withCredentials: true })
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
