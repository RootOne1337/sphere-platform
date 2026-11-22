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
  recoverable?: boolean;
  can: (permission: string) => boolean; canAccessRoute: (path: string) => boolean;
  retry: () => void;
}
const DENIED: Access = {
  verified: false, pending: true, failed: false, role: null,
  recoverable: false,
  can: () => false, canAccessRoute: () => false, retry: () => {},
};
const Context = createContext<Access>(DENIED);
export const useCapabilities = () => useContext(Context);
class UnverifiedCapabilitiesResponse extends Error {}

function authoritativeRefusal(error: unknown): boolean {
  if (error instanceof UnverifiedCapabilitiesResponse) return true;
  const status = (error as { response?: { status?: unknown } } | null)?.response?.status;
  return typeof status === 'number' && status >= 400 && status < 500 && status !== 408 && status !== 429;
}

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
        throw new UnverifiedCapabilitiesResponse('Неподтверждённый ответ о правах текущей сессии.');
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
    // This permits retaining memory, never grants. Unknown ownership, refusal
    // and authoritative role/grant changes must retire the private subtree.
    recoverable: Boolean(user && !roleChanged && !verified && !authoritativeRefusal(query.error)),
    can: permission => verified && grants.includes(permission),
    canAccessRoute: path => canAccessRoute(path, grants, verified),
    retry: () => { void query.refetch(); },
  };
  return <Context.Provider value={access}>{children}</Context.Provider>;
}

export function RouteAccessBoundary({ pathname, children }: { pathname: string; children: ReactNode }) {
  const access = useCapabilities();
  const user = useAuthStore(state => state.user);
  const version = useAuthStore(state => state.sessionVersion);
  if (pathname.split(/[?#]/, 1)[0].replace(/\/+$/, '') === '/scripts/builder') {
    const identity = JSON.stringify([version, user?.org_id, user?.id, user?.role, pathname]);
    return <RecoverableStudioBoundary key={identity} pathname={pathname} access={access}>{children}</RecoverableStudioBoundary>;
  }
  if (access.canAccessRoute(pathname)) return <>{children}</>;
  return <RouteAccessNotice pathname={pathname} access={access} />;
}

function RecoverableStudioBoundary({ pathname, access, children }: { pathname: string; access: Access; children: ReactNode }) {
  const allowed = access.canAccessRoute(pathname);
  const [retained, setRetained] = useState(allowed);
  const keep = allowed || Boolean(retained && access.recoverable);
  // Adjust only this boundary's render state; revocation removes the editor
  // before effects, while an initial unknown response never mounts it.
  if (retained !== keep) setRetained(keep);
  return <>
    {!allowed && <RouteAccessNotice pathname={pathname} access={access} retained={keep} />}
    {keep && <div hidden={!allowed} inert={!allowed} aria-hidden={!allowed || undefined} className={allowed ? 'contents' : 'hidden'}>{children}</div>}
  </>;
}

function RouteAccessNotice({ pathname, access, retained = false }: { pathname: string; access: Access; retained?: boolean }) {
  return <section className="mx-auto my-8 max-w-2xl space-y-4 rounded-2xl border border-border bg-card p-6 shadow-soft" role={access.pending ? 'status' : 'alert'}>
    <ShieldAlert className="h-7 w-7 text-muted-foreground" aria-hidden />
    <h1 className="text-xl font-semibold">{access.pending ? 'Проверяем доступ к разделу' : access.failed ? 'Не удалось проверить права' : 'Раздел недоступен для вашей роли'}</h1>
    <p className="break-words text-sm text-muted-foreground">{access.pending ? 'Получаем разрешения текущей сессии из API.' : access.failed ? 'Последний ответ о правах больше не используется. Проверьте соединение и повторите запрос.' : `Текущая роль: ${access.role || 'неизвестна'}. Для открытия ${pathname} требуется другое разрешение. Обратитесь к администратору организации.`}</p>
    {retained && <p className="text-sm text-muted-foreground">Редактор и результаты лаборатории сохранены в памяти этой страницы. Новые действия и управление Android заблокированы до проверки доступа. Не обновляйте страницу: несохранённая работа будет потеряна.</p>}
    <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={access.pending} onClick={access.retry}><RefreshCw className="mr-2 h-4 w-4" aria-hidden />Проверить доступ снова</Button>{access.canAccessRoute('/settings') && <Button asChild variant="ghost"><Link href="/settings">Мой профиль</Link></Button>}</div>
  </section>;
}
