'use client';
import { create } from 'zustand';
import { useState, useEffect } from 'react';
import axios from 'axios';

const REFRESH_TOKEN_KEY = 'sphere_refresh_token';
const SIGNED_OUT_KEY = 'sphere_signed_out';
export const AUTH_TIMEOUT_MS = 5000;

export function saveRefreshToken(token: string) {
  try { if (typeof window !== 'undefined') localStorage.setItem(REFRESH_TOKEN_KEY, token); } catch { /* Cookie-only browser. */ }
}
export function getRefreshToken(): string | null {
  try { return typeof window !== 'undefined' ? localStorage.getItem(REFRESH_TOKEN_KEY) : null; } catch { return null; }
}
export function clearRefreshToken() {
  try { if (typeof window !== 'undefined') localStorage.removeItem(REFRESH_TOKEN_KEY); } catch { /* Memory is still cleared. */ }
}
function signedOut(): boolean {
  if (useAuthStore.getState().explicitlySignedOut) return true;
  try { return typeof window !== 'undefined' && localStorage.getItem(SIGNED_OUT_KEY) === '1'; } catch { return false; }
}

type User = { id: string; email: string; role: string; org_id: string; mfa_enabled?: boolean };
export interface SessionTokens { access_token: string; refresh_token?: string; user: User }
interface AuthState {
  accessToken: string | null;
  user: User | null;
  sessionVersion: number;
  explicitlySignedOut: boolean;
  logoutWarning: string | null;
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
  explicitlySignedOut: false,
  logoutWarning: null,
  setAccessToken: (token) => set(s => ({ accessToken: token, explicitlySignedOut: false, sessionVersion: s.sessionVersion + 1 })),
  setUser: (user) => set(s => ({ user, sessionVersion: s.sessionVersion + 1 })),
  completeLogin: (tokens, version) => {
    if (get().sessionVersion !== version) return false;
    validateTokens(tokens);
    persistTokens(tokens);
    set({ accessToken: tokens.access_token, user: tokens.user, explicitlySignedOut: false, logoutWarning: null });
    return true;
  },
  logout: () => {
    // Publish the memory boundary even if the browser blocks storage access.
    set(s => ({ accessToken: null, user: null, explicitlySignedOut: true, sessionVersion: s.sessionVersion + 1 }));
    clearRefreshToken();
    try { if (typeof window !== 'undefined') localStorage.setItem(SIGNED_OUT_KEY, '1'); } catch { /* Keep the in-memory logout boundary. */ }
  },
}));

export function beginLogin(): number {
  useAuthStore.getState().logout();
  useAuthStore.setState({ logoutWarning: null });
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
  try { if (typeof window !== 'undefined') localStorage.removeItem(SIGNED_OUT_KEY); } catch { /* Cookie-only browser. */ }
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
    useAuthStore.setState({ accessToken: data.access_token, user: data.user, explicitlySignedOut: false });
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

/** Clear local access immediately, then revoke the captured server session without API retries. */
export async function signOut(): Promise<boolean> {
  const access = useAuthStore.getState().accessToken;
  const refresh = getRefreshToken();
  useAuthStore.getState().logout();
  const version = useAuthStore.getState().sessionVersion;
  useAuthStore.setState({ logoutWarning: null });
  try {
    await axios.post(`${process.env.NEXT_PUBLIC_API_URL ?? '/api/v1'}/auth/logout`, {}, {
      withCredentials: true,
      timeout: AUTH_TIMEOUT_MS,
      headers: { ...(access ? { Authorization: `Bearer ${access}` } : {}), ...(refresh ? { 'X-Refresh-Token': refresh } : {}) },
    });
    return true;
  } catch {
    if (useAuthStore.getState().sessionVersion === version) {
      useAuthStore.setState({ logoutWarning: 'Signed out on this browser. Server session revocation could not be confirmed.' });
    }
    return false;
  }
}
