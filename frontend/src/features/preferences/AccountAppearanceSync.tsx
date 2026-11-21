'use client';

import { createContext, useContext, useLayoutEffect, useState, type ReactNode } from 'react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { useThemeStore } from '@/src/shared/store/themeStore';
import { useUIStore } from '@/src/shared/store/useUIStore';
import {
  applyAppearance, appearanceChanges, DEFAULT_APPEARANCE, parsePreferenceProfile, readAppearance,
  type Appearance, type PreferenceProfile,
} from './accountAppearance';

type SyncStatus = 'local' | 'loading' | 'saving' | 'saved' | 'offline' | 'conflict';
const Context = createContext<{ status: SyncStatus; reload: () => void }>({ status: 'local', reload: () => undefined });
export const useAccountAppearance = () => useContext(Context);
const RESOURCE = '/user-preferences/me';
const DEBOUNCE_MS = 350;

function etag(revision: number): string {
  return '"ui-' + revision + '"';
}

export function AccountAppearanceSync({ children }: { children: ReactNode }) {
  const user = useAuthStore(state => state.user);
  const session = useAuthStore(state => state.sessionVersion);
  const [status, setStatus] = useState<SyncStatus>('local');
  const [retry, setRetry] = useState(0);
  const org = user?.org_id;
  const userId = user?.id;

  useLayoutEffect(() => {
    if (!org || !userId) return;
    const key = 'sphere-account-appearance:' + encodeURIComponent(org) + ':' + encodeURIComponent(userId);
    const controller = new AbortController();
    let baseline: PreferenceProfile | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let saving = false;
    let applying = false;
    let writesPaused = false;
    let lastLocal = readAppearance();
    const active = () => {
      const state = useAuthStore.getState();
      return !controller.signal.aborted && state.sessionVersion === session
        && state.user?.org_id === org && state.user?.id === userId;
    };
    const apply = (appearance: Appearance) => {
      applying = true;
      applyAppearance(appearance);
      lastLocal = appearance;
      applying = false;
    };
    const cache = (profile: PreferenceProfile) => {
      try { localStorage.setItem(key, JSON.stringify(profile)); } catch { /* Browser storage is optional. */ }
    };
    try {
      const raw = localStorage.getItem(key);
      baseline = raw ? parsePreferenceProfile(JSON.parse(raw), org, userId) : null;
    } catch { /* Ignore invalid or inaccessible cached data. */ }
    apply(baseline?.appearance ?? DEFAULT_APPEARANCE);

    const schedule = () => {
      if (!active() || !baseline || writesPaused || saving) return;
      clearTimeout(timer);
      timer = setTimeout(() => { void save(); }, DEBOUNCE_MS);
    };
    const save = async () => {
      if (!active() || !baseline || writesPaused || saving) return;
      const target = lastLocal;
      const patch = appearanceChanges(baseline.appearance, target);
      if (!Object.keys(patch).length) { setStatus('saved'); return; }
      saving = true;
      setStatus('saving');
      let succeeded = false;
      try {
        const response = await api.patch<unknown>(RESOURCE, patch, {
          headers: { 'If-Match': etag(baseline.revision) }, signal: controller.signal,
        });
        if (!active()) return;
        const next = parsePreferenceProfile(response.data, org, userId);
        if (response.headers?.etag !== etag(next.revision) || next.revision !== baseline.revision + 1
          || Object.keys(appearanceChanges(target, next.appearance)).length) {
          throw new Error('Invalid appearance revision');
        }
        const pending = appearanceChanges(target, lastLocal);
        baseline = next;
        cache(next);
        apply({ ...next.appearance, ...pending });
        setStatus(Object.keys(pending).length ? 'saving' : 'saved');
        succeeded = true;
      } catch (error) {
        if (!active()) return;
        const status = (error as { response?: { status?: unknown } } | null)?.response?.status;
        writesPaused = true;
        setStatus(status === 412 ? 'conflict' : 'offline');
      } finally {
        saving = false;
        if (succeeded && baseline && Object.keys(appearanceChanges(baseline.appearance, lastLocal)).length) schedule();
      }
    };
    const changed = () => {
      if (!active() || applying) return;
      const next = readAppearance();
      if (!Object.keys(appearanceChanges(lastLocal, next)).length) return;
      lastLocal = next;
      if (baseline && !writesPaused && !saving) setStatus('saving');
      schedule();
    };
    const unsubTheme = useThemeStore.subscribe(changed);
    const unsubUi = useUIStore.subscribe(changed);
    setStatus('loading');
    saving = true;
    const readStarted = lastLocal;
    const load = async () => {
      let pendingChanges = false;
      try {
        const response = await api.get<unknown>(RESOURCE, { signal: controller.signal });
        if (!active()) return;
        const next = parsePreferenceProfile(response.data, org, userId);
        if (response.headers?.etag !== etag(next.revision)) throw new Error('Invalid appearance revision');
        const pending = appearanceChanges(readStarted, lastLocal);
        baseline = next;
        cache(next);
        apply({ ...next.appearance, ...pending });
        pendingChanges = Object.keys(pending).length > 0;
        setStatus(pendingChanges ? 'saving' : 'saved');
      } catch (error) {
        if (!active()) return;
        const code = (error as { response?: { status?: unknown } } | null)?.response?.status;
        // A failed read never authorizes a write against a cached revision.
        writesPaused = true;
        setStatus(code === 404 ? 'local' : 'offline');
      } finally {
        saving = false;
        if (pendingChanges) schedule();
      }
    };
    void load();

    return () => {
      controller.abort();
      clearTimeout(timer);
      unsubTheme();
      unsubUi();
      applyAppearance(DEFAULT_APPEARANCE);
    };
  }, [org, userId, session, retry]);

  return <Context.Provider value={{ status, reload: () => setRetry(value => value + 1) }}>{children}</Context.Provider>;
}
