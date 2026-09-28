'use client';

import { useState } from 'react';
import { useUsers, useCreateUser, useUpdateRole, useDeactivateUser } from '@/lib/hooks/useUsers';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { AlertTriangle, ChevronLeft, ChevronRight, Plus, ShieldCheck, Users } from 'lucide-react';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';

const ROLES = ['viewer', 'script_runner', 'device_manager', 'org_admin', 'org_owner'] as const;
const ROLE_LABELS: Record<(typeof ROLES)[number], string> = {
  viewer: 'Наблюдатель',
  script_runner: 'Запуск сценариев',
  device_manager: 'Управление устройствами',
  org_admin: 'Администратор',
  org_owner: 'Владелец организации',
};

function formatDate(value: string | null) {
  if (!value) return 'Нет входов';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' });
}

export default function UsersPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading, isError, refetch } = useUsers(page);
  const createUser = useCreateUser();
  const updateRole = useUpdateRole();
  const deactivateUser = useDeactivateUser();
  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState<(typeof ROLES)[number]>('viewer');
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleCreate = async () => {
    try {
      await createUser.mutateAsync({ email: newEmail.trim(), password: newPassword, role: newRole });
      setNewEmail(''); setNewPassword(''); setNewRole('viewer'); setDialogOpen(false);
    } catch {
      // Keep entered values so the administrator can correct the request.
    }
  };

  const refreshAfterMutationError = () => { void refetch(); };

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Доступ и роли"
        title="Пользователи"
        description="Управляйте учётными записями организации, ролями и состоянием многофакторной аутентификации."
        actions={(
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild><Button><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Добавить пользователя</Button></DialogTrigger>
            <DialogContent aria-describedby={undefined}>
              <DialogHeader><DialogTitle>Новая учётная запись</DialogTitle></DialogHeader>
              <div className="space-y-4 pt-2">
                <div className="space-y-2"><Label htmlFor="new-user-email">Электронная почта</Label><Input id="new-user-email" type="email" autoComplete="email" value={newEmail} onChange={(event) => setNewEmail(event.target.value)} /></div>
                <div className="space-y-2"><Label htmlFor="new-user-password">Временный пароль</Label><Input id="new-user-password" type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /><p className="text-xs text-muted-foreground">Передайте пароль пользователю безопасным способом.</p></div>
                <div className="space-y-2"><Label htmlFor="new-user-role">Роль</Label><select id="new-user-role" value={newRole} onChange={(event) => setNewRole(event.target.value as (typeof ROLES)[number])} className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{ROLES.map((role) => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}</select></div>
                {createUser.isError && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">Не удалось создать пользователя. Проверьте адрес, пароль и права доступа.</p>}
                <Button onClick={() => { void handleCreate(); }} disabled={createUser.isPending || !newEmail.trim() || !newPassword} className="w-full">{createUser.isPending ? 'Создаём…' : 'Создать пользователя'}</Button>
              </div>
            </DialogContent>
          </Dialog>
        )}
      />

      {(updateRole.isError || deactivateUser.isError) && <div role="alert" className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />Не удалось сохранить изменение доступа. Данные перечитаны с сервера.</div>}

      {isError ? (
        <Card><CardContent className="flex flex-col gap-3 p-6 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-medium">Не удалось загрузить пользователей</p><p className="mt-1 text-sm text-muted-foreground">Проверьте доступ к API и повторите запрос.</p></div><Button type="button" variant="outline" onClick={() => { void refetch(); }}>Повторить</Button></CardContent></Card>
      ) : isLoading ? (
        <div className="space-y-3" aria-label="Загрузка пользователей" aria-busy="true">{Array.from({ length: 5 }, (_, index) => <div key={index} className="h-14 animate-pulse rounded-xl border border-border bg-card motion-reduce:animate-none" />)}</div>
      ) : (
        <Card className="overflow-hidden shadow-soft">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 bg-muted/30 px-5 py-4">
            <div className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary"><Users className="h-4 w-4" aria-hidden="true" /></span><div><p className="text-sm font-medium">Участники организации</p><p className="text-xs text-muted-foreground">{data?.total ?? 0} записей · страница {data?.page ?? page} из {data?.pages ?? 1}</p></div></div>
            <Badge variant="outline" className="rounded-full"><ShieldCheck className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />Роли применяются сервером</Badge>
          </div>
          {!data?.items.length ? (
            <CardContent className="p-10 text-center"><p className="font-medium">Пользователей нет</p><p className="mt-1 text-sm text-muted-foreground">Создайте учётную запись для участника организации.</p></CardContent>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm">
                <thead className="bg-muted/30 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground"><tr><th scope="col" className="px-5 py-3">Участник</th><th scope="col" className="px-5 py-3">Роль</th><th scope="col" className="px-5 py-3">Статус</th><th scope="col" className="px-5 py-3">MFA</th><th scope="col" className="px-5 py-3">Последний вход</th><th scope="col" className="px-5 py-3 text-right">Действия</th></tr></thead>
                <tbody className="divide-y divide-border/70">
                  {data?.items.map((user) => (
                    <tr key={user.id} className="transition-colors hover:bg-muted/30 motion-reduce:transition-none">
                      <td className="px-5 py-3.5"><p className="font-medium">{user.email}</p><p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{user.id}</p></td>
                      <td className="px-5 py-3.5"><select aria-label={`Роль пользователя ${user.email}`} value={user.role} onChange={(event) => updateRole.mutate({ userId: user.id, role: event.target.value }, { onError: refreshAfterMutationError })} disabled={updateRole.isPending || !user.is_active} className="h-9 min-w-48 rounded-lg border border-input bg-background px-2.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">{ROLES.map((role) => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}</select></td>
                      <td className="px-5 py-3.5"><Badge variant={user.is_active ? 'success' : 'secondary'} className="rounded-full">{user.is_active ? 'Активен' : 'Отключён'}</Badge></td>
                      <td className="px-5 py-3.5"><Badge variant={user.mfa_enabled ? 'success' : 'outline'} className="rounded-full">{user.mfa_enabled ? 'Включена' : 'Выключена'}</Badge></td>
                      <td className="px-5 py-3.5 text-xs text-muted-foreground">{formatDate(user.last_login_at)}</td>
                      <td className="px-5 py-3.5 text-right">{user.is_active && <Button type="button" size="sm" variant="outline" className="text-destructive hover:bg-destructive/10 hover:text-destructive" onClick={() => { if (window.confirm(`Отключить пользователя ${user.email}?`)) deactivateUser.mutate(user.id, { onError: refreshAfterMutationError }); }} disabled={deactivateUser.isPending}>Отключить</Button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data && data.pages > 1 && <div className="flex items-center justify-between gap-3 border-t border-border/70 px-5 py-3"><p className="text-xs text-muted-foreground">Страница {page} из {data.pages}</p><div className="flex items-center gap-2"><Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}><ChevronLeft className="mr-1 h-4 w-4" aria-hidden="true" />Назад</Button><Button size="sm" variant="outline" disabled={page >= data.pages} onClick={() => setPage((current) => current + 1)}>Далее<ChevronRight className="ml-1 h-4 w-4" aria-hidden="true" /></Button></div></div>}
        </Card>
      )}
    </PageFrame>
  );
}
