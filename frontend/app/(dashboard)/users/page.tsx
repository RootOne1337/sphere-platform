'use client';

import { useState } from 'react';
import { useUsers } from '@/lib/hooks/useUsers';
import { useAuthStore } from '@/lib/store';
import { canReadUsers, canManageUserRole, canChangeUserRole, USER_ROLE_LABELS, USER_ROLES } from '@/src/features/users/access';
import { CreateUserDialog, UserAccessDialog, type UserAccessAction } from '@/src/features/users/UserDialogs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ChevronLeft, ChevronRight, Plus, ShieldCheck, Users } from 'lucide-react';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';

function formatDate(value: string | null) {
  if (!value) return 'Нет входов';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' });
}

export default function UsersPage() {
  const actor = useAuthStore(state => state.user);
  const sessionVersion = useAuthStore(state => state.sessionVersion);
  const scope = `${actor?.id}:${actor?.org_id}:${actor?.role}:${sessionVersion}`;
  return <UsersManagement key={scope} actor={actor} scope={scope} />;
}

function UsersManagement({ actor, scope }: { actor: ReturnType<typeof useAuthStore.getState>['user']; scope: string }) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<'all' | 'active' | 'inactive'>('all');
  const platformScope = actor?.role === 'super_admin';
  const allowed = Boolean(actor && canReadUsers(actor.role));
  const { data, isLoading, isError, refetch } = useUsers(page, 50, { enabled: allowed, scope });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [action, setAction] = useState<UserAccessAction | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const query = search.trim().toLowerCase();
  const filtered = Boolean(query) || status !== 'all';
  const visibleUsers = data?.items.filter(user => (
    (!query || user.email.toLowerCase().includes(query) || user.id.toLowerCase().includes(query)
      || (platformScope && user.org_id.toLowerCase().includes(query)))
    && (status === 'all' || user.is_active === (status === 'active'))
  )) ?? [];
  const available = allowed && Boolean(data) && !isError;
  const currentTarget = action ? data?.items.find(user => user.id === action.user.id) : undefined;
  const actionAvailable = available && Boolean(action && currentTarget && currentTarget.org_id === action.user.org_id
    && currentTarget.role === action.user.role && currentTarget.is_active === action.user.is_active
    && actor && canManageUserRole(actor.role, currentTarget.role)
    && (action.kind === 'role' ? canChangeUserRole(actor.role) && canManageUserRole(actor.role, action.role) : currentTarget.id !== actor.id));
  if (!allowed) return <PageFrame><PageHeading title="Пользователи" description="Управление доступом организации." /><Card><CardContent className="space-y-2 p-6" role="alert"><p className="font-medium">Нет доступа к пользователям</p><p className="text-sm text-muted-foreground">Нужна роль администратора или владельца организации. Сервер проверяет права каждого запроса.</p></CardContent></Card></PageFrame>;

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Доступ и роли"
        title="Пользователи"
        description={platformScope ? 'Управляйте учётными записями всех организаций платформы.' : 'Управляйте учётными записями вашей организации, ролями и MFA.'}
        actions={(
          <Button disabled={!available} onClick={() => setDialogOpen(true)}><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Добавить пользователя</Button>
        )}
      />

      {notice && <p role="status" className="rounded-xl border border-success/30 bg-success/5 p-3 text-sm">{notice}</p>}

      {isError ? (
        <Card><CardContent className="flex flex-col gap-3 p-6 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-medium">Не удалось загрузить пользователей</p><p className="mt-1 text-sm text-muted-foreground">Проверьте доступ к API и повторите запрос.</p></div><Button type="button" variant="outline" onClick={() => { void refetch(); }}>Повторить</Button></CardContent></Card>
      ) : isLoading ? (
        <div className="space-y-3" aria-label="Загрузка пользователей" aria-busy="true">{Array.from({ length: 5 }, (_, index) => <div key={index} className="h-14 animate-pulse rounded-xl border border-border bg-card motion-reduce:animate-none" />)}</div>
      ) : (
        <Card className="overflow-hidden shadow-soft">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 bg-muted/30 px-5 py-4">
            <div className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><Users className="h-4 w-4" aria-hidden="true" /></span><div><p className="text-sm font-medium">{platformScope ? 'Пользователи всех организаций' : 'Участники вашей организации'}</p><p className="text-xs text-muted-foreground">{data?.total ?? 0} записей · страница {data?.page ?? page} из {data?.pages ?? 1}</p></div></div>
            <Badge variant="outline" className="rounded-full"><ShieldCheck className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />Роли применяются сервером</Badge>
          </div>
          {Boolean(data?.items.length) && <div className="flex flex-wrap items-end gap-3 border-b border-border/70 px-5 py-3">
            <div className="min-w-44 flex-1 space-y-1">
              <label htmlFor="user-page-search" className="text-xs font-medium">Поиск на этой странице</label>
              <Input id="user-page-search" value={search} maxLength={254} disabled={Boolean(action)}
                placeholder={platformScope ? 'Почта, ID пользователя или организации' : 'Почта или ID пользователя'}
                onChange={event => setSearch(event.target.value)} />
            </div>
            <div className="space-y-1">
              <label htmlFor="user-page-status" className="block text-xs font-medium">Статус аккаунта</label>
              <select id="user-page-status" value={status} disabled={Boolean(action)} onChange={event => {
                const value = event.target.value;
                if (value === 'all' || value === 'active' || value === 'inactive') setStatus(value);
              }} className="h-10 rounded-md border border-input bg-background px-2.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <option value="all">Все статусы</option><option value="active">Активные</option><option value="inactive">Отключённые</option>
              </select>
            </div>
            {filtered && <Button type="button" variant="outline" disabled={Boolean(action)} onClick={() => { setSearch(''); setStatus('all'); }}>Сбросить фильтры</Button>}
          </div>}
          {!data?.items.length ? (
            <CardContent className="p-10 text-center"><p className="font-medium">Пользователей нет</p><p className="mt-1 text-sm text-muted-foreground">Создайте учётную запись для участника организации.</p></CardContent>
          ) : visibleUsers.length === 0 ? (
            <CardContent className="p-8 text-center"><p className="font-medium">На этой странице совпадений нет</p><p className="mt-1 text-sm text-muted-foreground">Измените фильтры или откройте другую страницу.</p></CardContent>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm">
                <thead className="bg-muted/30 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground"><tr><th scope="col" className="px-5 py-3">Участник</th>{platformScope && <th scope="col" className="px-5 py-3">Организация</th>}<th scope="col" className="px-5 py-3">Роль</th><th scope="col" className="px-5 py-3">Статус</th><th scope="col" className="px-5 py-3">MFA</th><th scope="col" className="px-5 py-3">Последний вход</th><th scope="col" className="px-5 py-3 text-right">Действия</th></tr></thead>
                <tbody className="divide-y divide-border/70">
                  {visibleUsers.map((user) => (
                    <tr key={user.id} className="transition-colors hover:bg-muted/30 motion-reduce:transition-none">
                      <td className="px-5 py-3.5"><p className="font-medium">{user.email}</p><p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{user.id}</p></td>
                      {platformScope && <td className="break-all px-5 py-3.5 font-mono text-xs">{user.org_id}</td>}
                      <td className="px-5 py-3.5"><select aria-label={`Роль пользователя ${user.email}`} value={user.role}
                        onChange={(event) => { if (event.target.value !== user.role) { setNotice(null); setAction({ kind: 'role', user: { ...user }, role: event.target.value }); } }}
                        disabled={Boolean(action) || !user.is_active || !actor || !canChangeUserRole(actor.role) || !canManageUserRole(actor.role, user.role)}
                        className="h-9 min-w-48 rounded-lg border border-input bg-background px-2.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
                        <option value={user.role}>{USER_ROLE_LABELS[user.role as keyof typeof USER_ROLE_LABELS] ?? user.role}</option>
                        {USER_ROLES.filter(role => role !== user.role && actor && canManageUserRole(actor.role, role)).map(role => <option key={role} value={role}>{USER_ROLE_LABELS[role]}</option>)}
                      </select></td>
                      <td className="px-5 py-3.5"><Badge variant={user.is_active ? 'success' : 'secondary'} className="rounded-full">{user.is_active ? 'Активен' : 'Отключён'}</Badge></td>
                      <td className="px-5 py-3.5"><Badge variant={user.mfa_enabled ? 'success' : 'outline'} className="rounded-full">{user.mfa_enabled ? 'Включена' : 'Выключена'}</Badge></td>
                      <td className="px-5 py-3.5 text-xs text-muted-foreground">{formatDate(user.last_login_at)}</td>
                      <td className="px-5 py-3.5 text-right">{user.is_active && <Button type="button" size="sm" variant="outline" className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                        title={user.id === actor?.id ? 'Нельзя отключить себя' : !actor || !canManageUserRole(actor.role, user.role) ? 'Нет права отключить эту роль' : undefined}
                        onClick={() => { setNotice(null); setAction({ kind: 'deactivate', user: { ...user } }); }} disabled={Boolean(action) || user.id === actor?.id || !actor || !canManageUserRole(actor.role, user.role)}>Отключить</Button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data && data.pages > 1 && <div className="flex items-center justify-between gap-3 border-t border-border/70 px-5 py-3"><p className="text-xs text-muted-foreground">Страница {page} из {data.pages}</p><div className="flex items-center gap-2"><Button size="sm" variant="outline" disabled={page <= 1 || Boolean(action)} onClick={() => setPage((current) => current - 1)}><ChevronLeft className="mr-1 h-4 w-4" aria-hidden="true" />Назад</Button><Button size="sm" variant="outline" disabled={page >= data.pages || Boolean(action)} onClick={() => setPage((current) => current + 1)}>Далее<ChevronRight className="ml-1 h-4 w-4" aria-hidden="true" /></Button></div></div>}
        </Card>
      )}
      {dialogOpen && actor && <CreateUserDialog actorRole={actor.role} orgId={actor.org_id} available={available} onClose={() => setDialogOpen(false)} onSaved={(message) => { setDialogOpen(false); setNotice(message); }} />}
      {action && <UserAccessDialog action={action} available={actionAvailable} onClose={() => setAction(null)} onRefresh={() => { void refetch(); }} onSaved={(message) => { setAction(null); setNotice(message); }} />}
    </PageFrame>
  );
}
