'use client';
import { create } from 'zustand';
import { useState, useEffect } from 'react';
import axios from 'axios';

const REFRESH_TOKEN_KEY = 'sphere_refresh_token';
const SIGNED_OUT_KEY = 'sphere_signed_out';
export const AUTH_TIMEOUT_MS = 5000;

export function saveRefreshToken(token: string) {
  if (typeof window !== 'undefined') localStorage.setItem(REFRESH_TOKEN_KEY, token);
}
export function getRefreshToken(): string | null {
  return typeof window !== 'undefined' ? localStorage.getItem(REFRESH_TOKEN_KEY) : null;
}
export function clearRefreshToken() {
  if (typeof window !== 'undefined') localStorage.removeItem(REFRESH_TOKEN_KEY);
}
function signedOut(): boolean {
  return typeof window !== 'undefined' && localStorage.getItem(SIGNED_OUT_KEY) === '1';
}

type User = { id: string; email: string; role: string; org_id: string; mfa_enabled?: boolean };
export interface SessionTokens { access_token: string; refresh_token?: string; user: User }
interface AuthState {
  accessToken: string | null;
  user: User | null;
  sessionVersion: number;
  setAccessToken: (token: string) => void;
  setUser: (user: User | null) => void;
  completeLogin: (tokens: SessionTokens, version: number) => boolean;
  logout: () => void;
}

// Access tokens stay in memory. A new login/logout invalidates outstanding work.
export const useAuthStore = create<AuthState>()((set, get) => ({
  accessToken: null,
  user: null,
  sessionVersion: 0,
  setAccessToken: (token) => set(s => ({ accessToken: token, sessionVersion: s.sessionVersion + 1 })),
  setUser: (user) => set(s => ({ user, sessionVersion: s.sessionVersion + 1 })),
  completeLogin: (tokens, version) => {
    if (get().sessionVersion !== version) return false;
    validateTokens(tokens);
    persistTokens(tokens);
    set({ accessToken: tokens.access_token, user: tokens.user });
    return true;
  },
  logout: () => {
    // Publish the memory boundary even if the browser blocks storage access.
    set(s => ({ accessToken: null, user: null, sessionVersion: s.sessionVersion + 1 }));
    clearRefreshToken();
    if (typeof window !== 'undefined') localStorage.setItem(SIGNED_OUT_KEY, '1');
  },
}));

export function beginLogin(): number {
  useAuthStore.getState().logout();
  return useAuthStore.getState().sessionVersion;
}

export class SessionChangedError extends Error {
  constructor() { super('Session changed while the request was in flight'); this.name = 'SessionChangedError'; }
}
export function assertSession(version: number) {
  if (useAuthStore.getState().sessionVersion !== version) throw new SessionChangedError();
}
function validateTokens(data: SessionTokens) {
  if (typeof data.access_token !== 'string' || !data.access_token || !data.user?.id || !data.user.org_id) {
    throw new Error('Invalid authentication response');
  }
}
function persistTokens(data: SessionTokens) {
  if (data.refresh_token) saveRefreshToken(data.refresh_token);
  if (typeof window !== 'undefined') localStorage.removeItem(SIGNED_OUT_KEY);
}

let refreshing: { version: number; promise: Promise<string> } | null = null;

/** One refresh per session, shared by startup and HTTP retries. Never restore a retired session. */
export function refreshSession(version = useAuthStore.getState().sessionVersion): Promise<string> {
  assertSession(version);
  if (signedOut()) return Promise.reject(new SessionChangedError());
  if (refreshing?.version === version) return refreshing.promise;
  const stored = getRefreshToken();
  const promise = axios.post<SessionTokens>(
    `${process.env.NEXT_PUBLIC_API_URL ?? '/api/v1'}/auth/refresh`, {},
    { withCredentials: true, timeout: AUTH_TIMEOUT_MS, headers: stored ? { 'X-Refresh-Token': stored } : {} },
  ).then(({ data }) => {
    assertSession(version);
    validateTokens(data);
    const user = useAuthStore.getState().user;
    if (user && (user.id !== data.user.id || user.org_id !== data.user.org_id)) {
      throw new Error('Refresh identity does not match the active session');
    }
    // Rotation preserves the version; queued requests still belong to this identity.
    persistTokens(data);
    useAuthStore.setState({ accessToken: data.access_token, user: data.user });
    return data.access_token;
  }).catch(error => {
    if (useAuthStore.getState().sessionVersion === version) useAuthStore.getState().logout();
    throw error;
  }).finally(() => {
    if (refreshing?.promise === promise) refreshing = null;
  });
  refreshing = { version, promise };
  return promise;
}

export function useInitAuth(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let mounted = true;
    const state = useAuthStore.getState();
    if ((state.accessToken && state.user) || signedOut()) { setReady(true); return; }
    void refreshSession(state.sessionVersion).catch(() => undefined).finally(() => {
      if (mounted) setReady(true);
    });
    return () => { mounted = false; };
  }, []);
  return ready;
}
