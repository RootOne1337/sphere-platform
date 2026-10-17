'use client';

import { useEffect, useRef, useState } from 'react';
import { useCreateUser, useDeactivateUser, useUpdateRole, type UserInfo } from '@/lib/hooks/useUsers';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { canManageUserRole, USER_ROLE_LABELS, USER_ROLES } from './access';
import { describeUserFailure, type UserFailure, type UserField } from './errors';

function useDialogLifetime() {
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  return mounted;
}
export function CreateUserDialog({ actorRole, orgId, available, onClose, onSaved }: {
  actorRole: string; orgId: string; available: boolean; onClose: () => void; onSaved: (message: string) => void;
}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('viewer');
  const [failure, setFailure] = useState<UserFailure | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const lock = useRef(false);
  const mounted = useDialogLifetime();
  const create = useCreateUser(orgId);
  const pending = create.isPending;
  const allowedRoles = USER_ROLES.filter(candidate => canManageUserRole(actorRole, candidate));
  function focusField(fields: UserFailure['fields']) {
    const field = (['email', 'password', 'role'] as UserField[]).find(name => fields[name]);
    if (field) formRef.current?.querySelector<HTMLElement>(`#new-user-${field}`)?.focus();
  }
  function clearField(field: UserField) {
    setFailure(current => current ? { ...current, fields: { ...current.fields, [field]: undefined } } : null);
  }
  async function submit() {
    if (lock.current || !available) return;
    const fields: UserFailure['fields'] = {};
    const count = Array.from(password).length;
    if (!email.trim() || !formRef.current?.querySelector<HTMLInputElement>('#new-user-email')?.validity.valid) fields.email = 'Введите корректный адрес электронной почты.';
    if (count < 8 || count > 128) fields.password = 'Пароль должен содержать от 8 до 128 символов.';
    if (!canManageUserRole(actorRole, role)) fields.role = 'Нет права назначить выбранную роль.';
    if (Object.keys(fields).length) { setFailure({ message: 'Исправьте отмеченные поля.', fields }); focusField(fields); return; }
    lock.current = true; setFailure(null);
    try {
      const confirmed = await create.mutateAsync({ email: email.trim(), password, role });
      if (mounted.current) { setPassword(''); onSaved(`Создан пользователь ${confirmed.email}.`); }
    } catch (error) {
      if (mounted.current) { const next = describeUserFailure(error); setFailure(next); focusField(next.fields); }
    } finally { lock.current = false; }
  }
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !lock.current) onClose(); }}>
      <DialogContent aria-describedby="user-create-description">
        <DialogHeader><DialogTitle>Новая учётная запись</DialogTitle><DialogDescription id="user-create-description">Пользователь получит доступ к вашей организации. Доступные роли определены вашей текущей ролью.</DialogDescription></DialogHeader>
        <form ref={formRef} className="space-y-4 pt-2" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <div className="space-y-2"><Label htmlFor="new-user-email">Электронная почта</Label>
            <Input id="new-user-email" type="email" required autoComplete="email" value={email} disabled={pending} aria-invalid={Boolean(failure?.fields.email)} aria-describedby={failure?.fields.email ? 'user-email-error' : undefined}
              onInvalid={() => setFailure({ message: 'Исправьте отмеченные поля.', fields: { email: 'Введите корректный адрес электронной почты.' } })}
              onChange={(event) => { setEmail(event.target.value); clearField('email'); }} />
            {failure?.fields.email && <p id="user-email-error" className="text-sm text-destructive">{failure.fields.email}</p>}
          </div>
          <div className="space-y-2"><Label htmlFor="new-user-password">Временный пароль</Label>
            <Input id="new-user-password" type="password" required autoComplete="new-password" value={password} disabled={pending} aria-invalid={Boolean(failure?.fields.password)} aria-describedby="user-password-help user-password-error"
              onChange={(event) => { setPassword(event.target.value); clearField('password'); }} />
            <p id="user-password-help" className="text-xs text-muted-foreground">От 8 до 128 символов. Передайте пароль пользователю безопасным способом.</p>
            <p id="user-password-error" className="text-sm text-destructive">{failure?.fields.password}</p>
          </div>
          <div className="space-y-2"><Label htmlFor="new-user-role">Роль</Label>
            <select id="new-user-role" value={role} disabled={pending} aria-invalid={Boolean(failure?.fields.role)} aria-describedby={failure?.fields.role ? 'user-role-error' : undefined}
              onChange={(event) => { setRole(event.target.value); clearField('role'); }} className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
              {allowedRoles.map(candidate => <option key={candidate} value={candidate}>{USER_ROLE_LABELS[candidate]}</option>)}
            </select>
            {failure?.fields.role && <p id="user-role-error" className="text-sm text-destructive">{failure.fields.role}</p>}
          </div>
          {!available && <p role="alert" className="text-sm text-destructive">Каталог пользователей недоступен. Обновите список перед записью.</p>}
          {failure && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{failure.message}</p>}
          <DialogFooter><Button type="button" variant="outline" disabled={pending} onClick={onClose}>Отмена</Button><Button type="submit" disabled={pending || !available}>{pending ? 'Создаём…' : 'Создать пользователя'}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export type UserAccessAction = { kind: 'role'; user: UserInfo; role: string } | { kind: 'deactivate'; user: UserInfo };
export function UserAccessDialog({ action, available, onClose, onSaved, onRefresh }: {
  action: UserAccessAction; available: boolean; onClose: () => void; onSaved: (message: string) => void; onRefresh: () => void;
}) {
  const updateRole = useUpdateRole();
  const deactivate = useDeactivateUser();
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  const mounted = useDialogLifetime();
  const pending = updateRole.isPending || deactivate.isPending;
  const user = action.user;
  const self = useAuthStore(state => state.user?.id === user.id);
  async function submit() {
    if (!available || lock.current) return;
    lock.current = true; setError(null);
    try {
      if (action.kind === 'role') {
        const confirmed = await updateRole.mutateAsync({ userId: user.id, role: action.role, orgId: user.org_id });
        if (mounted.current) {
          onSaved(`Роль пользователя ${user.email} изменена: ${USER_ROLE_LABELS[action.role as keyof typeof USER_ROLE_LABELS] ?? action.role}.`);
          const current = useAuthStore.getState().user;
          if (current?.id === confirmed.id && current.org_id === confirmed.org_id) useAuthStore.getState().setUser({ ...current, role: confirmed.role });
        }
      } else {
        await deactivate.mutateAsync(user.id);
        if (mounted.current) onSaved(`Пользователь ${user.email} отключён.`);
      }
    } catch (failure) { if (mounted.current) { setError(describeUserFailure(failure).message); onRefresh(); } }
    finally { lock.current = false; }
  }
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !lock.current) onClose(); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>{action.kind === 'role' ? 'Изменение роли' : 'Отключение пользователя'}</DialogTitle>
          <DialogDescription>{action.kind === 'role' ? 'Изменяются права указанной учётной записи. Защиту последнего владельца проверяет сервер.' : 'Учётная запись сохранится, но доступ к системе будет отключён.'}</DialogDescription>
        </DialogHeader>
        <div className="space-y-2 rounded-lg bg-muted p-3 text-sm"><p className="break-all font-medium">{user.email}</p><p className="break-all font-mono text-xs text-muted-foreground">{user.id} · {user.org_id}</p>
          {action.kind === 'role' && <p>{USER_ROLE_LABELS[user.role as keyof typeof USER_ROLE_LABELS] ?? user.role} → {USER_ROLE_LABELS[action.role as keyof typeof USER_ROLE_LABELS] ?? action.role}</p>}
        </div>
        {self && <p className="text-sm text-warning">Вы меняете собственные права. Доступные действия после подтверждения могут измениться.</p>}
        {!available && <p role="alert" className="text-sm text-destructive">Пользователь или его права изменились, либо каталог недоступен. Закройте окно и перечитайте список.</p>}
        {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{user.email}: {error}</p>}
        <DialogFooter><Button type="button" variant="outline" disabled={pending} onClick={onClose}>Отмена</Button><Button type="button" variant={action.kind === 'deactivate' ? 'destructive' : 'default'} disabled={pending || !available} onClick={() => { void submit(); }}>{pending ? 'Сохраняем…' : action.kind === 'role' ? 'Изменить роль' : 'Отключить пользователя'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
