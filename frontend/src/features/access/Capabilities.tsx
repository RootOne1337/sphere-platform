'use client';

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { ShieldAlert, RefreshCw } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/src/shared/ui/button';
import { canAccessRoute } from './routeAccess';
import { useInspectorStore } from '@/src/features/inspector/inspectorStore';
import { useCommandPaletteStore } from '@/src/features/navigation/commandPaletteStore';

interface Response {
  schema_version: 1; user_id: string; org_id: string; role: string; permissions: string[];
}
interface Access {
  verified: boolean; pending: boolean; failed: boolean; role: string | null;
  can: (permission: string) => boolean; canAccessRoute: (path: string) => boolean;
  retry: () => void;
}
const DENIED: Access = {
  verified: false, pending: true, failed: false, role: null,
  can: () => false, canAccessRoute: () => false, retry: () => {},
};
const Context = createContext<Access>(DENIED);
export const useCapabilities = () => useContext(Context);

export function PermissionNotice({ permission, action }: { permission: string; action: string }) {
  const access = useCapabilities();
  if (access.can(permission)) return null;
  return <p role="status" className="rounded-lg border border-border bg-muted/40 p-3 text-sm text-muted-foreground">
    {access.pending ? `Проверяем права: ${action} пока недоступно.`
      : access.failed ? `Не удалось подтвердить права: ${action} недоступно до успешной проверки.`
      : `Текущие права не разрешают ${action}. Обратитесь к администратору организации.`}
  </p>;
}

export function CapabilitiesProvider({ children }: { children: ReactNode }) {
  const user = useAuthStore(state => state.user);
  const version = useAuthStore(state => state.sessionVersion);
  const [now, setNow] = useState(Date.now);
  useEffect(() => () => {
    // These stores outlive React Query. Never reopen a former identity's selection.
    useInspectorStore.getState().closeInspector();
    useCommandPaletteStore.getState().close();
  }, []);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(timer);
  }, []);
  const query = useQuery({
    queryKey: ['capabilities', version, user?.org_id, user?.id, user?.role],
    enabled: Boolean(user), retry: false, staleTime: 30_000, refetchInterval: 60_000,
    queryFn: async ({ signal }) => {
      const { data } = await api.get<Response>('/auth/capabilities', { signal });
      if (data?.schema_version !== 1 || data.user_id !== user?.id || data.org_id !== user?.org_id
        || typeof data.role !== 'string' || !Array.isArray(data.permissions)
        || data.permissions.length > 256 || !data.permissions.every(p => typeof p === 'string' && p.length <= 128)) {
        throw new Error('Неподтверждённый ответ о правах текущей сессии.');
      }
      return data;
    },
  });
  const fresh = query.dataUpdatedAt > 0 && Math.max(now, Date.now()) - query.dataUpdatedAt <= 90_000;
  const roleChanged = Boolean(user && query.data && query.data.role !== user.role);
  useEffect(() => {
    if (!roleChanged || !fresh || query.isError || !query.data || !user) return;
    const current = useAuthStore.getState();
    if (current.sessionVersion !== version || current.user?.id !== user.id || current.user.org_id !== user.org_id) return;
    // Providers remount the private query client when role changes; other pages
    // must not continue using their cached administrative identity either.
    useAuthStore.setState({ user: { ...current.user, role: query.data.role } });
  }, [roleChanged, fresh, query.isError, query.data, user, version]);
  const verified = Boolean(user && query.data && fresh && !query.isError && !roleChanged);
  const grants = verified ? query.data!.permissions : [];
  const access: Access = {
    verified, pending: query.isPending || (!query.isError && roleChanged) || (!verified && query.isFetching),
    failed: query.isError || Boolean(query.data && !fresh), role: query.data?.role ?? null,
    can: permission => verified && grants.includes(permission),
    canAccessRoute: path => canAccessRoute(path, grants, verified),
    retry: () => { void query.refetch(); },
  };
  return <Context.Provider value={access}>{children}</Context.Provider>;
}

export function RouteAccessBoundary({ pathname, children }: { pathname: string; children: ReactNode }) {
  const access = useCapabilities();
  if (access.canAccessRoute(pathname)) return <>{children}</>;
  return <section className="mx-auto my-8 max-w-2xl space-y-4 rounded-2xl border border-border bg-card p-6 shadow-soft" role={access.pending ? 'status' : 'alert'}>
    <ShieldAlert className="h-7 w-7 text-muted-foreground" aria-hidden />
    <h1 className="text-xl font-semibold">{access.pending ? 'Проверяем доступ к разделу' : access.failed ? 'Не удалось проверить права' : 'Раздел недоступен для вашей роли'}</h1>
    <p className="break-words text-sm text-muted-foreground">{access.pending ? 'Получаем разрешения текущей сессии из API.' : access.failed ? 'Последний ответ о правах больше не используется. Проверьте соединение и повторите запрос.' : `Текущая роль: ${access.role || 'неизвестна'}. Для открытия ${pathname} требуется другое разрешение. Обратитесь к администратору организации.`}</p>
    <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={access.pending} onClick={access.retry}><RefreshCw className="mr-2 h-4 w-4" aria-hidden />Проверить доступ снова</Button>{access.canAccessRoute('/settings') && <Button asChild variant="ghost"><Link href="/settings">Мой профиль</Link></Button>}</div>
  </section>;
}
