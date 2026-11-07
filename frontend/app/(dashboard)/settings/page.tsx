'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, Copy, Eye, EyeOff, KeyRound, Plus, RefreshCw, ShieldCheck, UserRound } from 'lucide-react';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { toast } from 'sonner';

interface AccountProfile {
  id: string; org_id: string; email: string; role: string;
  is_active: boolean; mfa_enabled: boolean;
  created_at?: string; last_login_at?: string | null;
}
interface APIKeyItem {
  id: string; name: string; key_prefix: string; permissions: string[]; is_active: boolean;
  expires_at: string | null; last_used_at: string | null; created_at: string;
}
interface APIKeyCreated { raw_key: string; name: string }
interface MFASetupData { qr_code: string; secret: string }
type Confirmation = { kind: 'mfa' } | { kind: 'key'; key: APIKeyItem };
type TabId = 'profile' | 'mfa' | 'apikeys';

function formatDate(value?: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return 'Нет данных';
  return new Date(value).toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' });
}
function Section({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return <section className="min-w-0 rounded-xl border border-border bg-card shadow-sm">
    <div className="border-b border-border p-5 sm:p-6"><h2 className="text-base font-semibold">{title}</h2><p className="mt-1 text-sm text-muted-foreground">{description}</p></div>
    <div className="p-5 sm:p-6">{children}</div>
  </section>;
}
function ErrorNotice({ message, children }: { message: string; children?: ReactNode }) {
  return <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
    <div className="flex min-w-0 flex-1 items-start gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden="true" /><p className="break-words">{message}</p></div>{children}
  </div>;
}

export default function SettingsPage() {
  const user = useAuthStore((state) => state.user);
  const client = useQueryClient();
  const profileKey = ['settings', 'profile', user?.id] as const;
  const keysKey = ['settings', 'api-keys', user?.org_id] as const;
  const [tab, setTab] = useState<TabId>('profile');
  const [createOpen, setCreateOpen] = useState(false);
  const [keyName, setKeyName] = useState('');
  const [newKey, setNewKey] = useState<APIKeyCreated | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [setup, setSetup] = useState<MFASetupData | null>(null);
  const [code, setCode] = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const actionLock = useRef(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (copyTimer.current) clearTimeout(copyTimer.current); }, []);

  const profile = useQuery({
    queryKey: profileKey, enabled: Boolean(user), retry: false, staleTime: 30_000, refetchInterval: 60_000,
    queryFn: async (): Promise<AccountProfile> => {
      const { data } = await api.get<AccountProfile>('/auth/me');
      if (!data || data.id !== user?.id || data.org_id !== user?.org_id || typeof data.mfa_enabled !== 'boolean') throw new Error('Invalid profile response');
      return data;
    },
  });
  const keys = useQuery({
    queryKey: keysKey, enabled: tab === 'apikeys' && Boolean(user), retry: false, staleTime: 30_000,
    queryFn: async (): Promise<APIKeyItem[]> => {
      const { data } = await api.get<APIKeyItem[]>('/auth/api-keys');
      if (!Array.isArray(data) || data.some((key) => !key || typeof key.id !== 'string' || !Array.isArray(key.permissions))) throw new Error('Invalid API keys response');
      return data;
    },
  });
  const createKey = useMutation({
    gcTime: 0,
    retry: false,
    mutationFn: async (name: string) => {
      const { data } = await api.post<APIKeyCreated>('/auth/api-keys', { name });
      if (!data || typeof data.raw_key !== 'string' || !data.raw_key) throw new Error('Key receipt missing');
      return data;
    },
    onSuccess: (data) => { setNewKey(data); void client.invalidateQueries({ queryKey: keysKey }); },
  });
  const revokeKey = useMutation({
    retry: false,
    mutationFn: async (id: string) => { await api.delete(`/auth/api-keys/${id}`); },
    onSuccess: () => { setConfirmation(null); void client.invalidateQueries({ queryKey: keysKey }); toast.success('API-ключ отозван'); },
  });
  const setupMfa = useMutation({
    gcTime: 0,
    retry: false,
    mutationFn: async () => {
      const { data } = await api.post<MFASetupData>('/auth/mfa/setup');
      if (!data || typeof data.secret !== 'string' || !data.secret || typeof data.qr_code !== 'string' || !data.qr_code) throw new Error('MFA setup receipt missing');
      return data;
    },
    onSuccess: (data) => { setSetup(data); setCode(''); setShowSecret(false); },
  });
  const updateMfaSnapshot = (enabled: boolean) => {
    client.setQueryData<AccountProfile>(profileKey, (previous) => previous ? { ...previous, mfa_enabled: enabled } : previous);
    void client.invalidateQueries({ queryKey: profileKey });
    setSetup(null); setCode(''); setShowSecret(false);
    setupMfa.reset();
  };
  const verifyMfa = useMutation({
    retry: false,
    mutationFn: async (value: string) => { await api.post('/auth/mfa/verify-setup', { code: value }); },
    onSuccess: () => { updateMfaSnapshot(true); toast.success('MFA включена'); },
  });
  const disableMfa = useMutation({
    retry: false,
    mutationFn: async () => { await api.delete('/auth/mfa'); },
    onSuccess: () => { updateMfaSnapshot(false); setConfirmation(null); toast.success('MFA отключена'); },
  });
  const busy = createKey.isPending || revokeKey.isPending || setupMfa.isPending || verifyMfa.isPending || disableMfa.isPending;
  const canChangeMfa = profile.isSuccess && !profile.isFetching;

  // Guard the same render too: React pending state alone cannot stop two rapid submits.
  const runAction = async (action: () => Promise<unknown>, fallback: string) => {
    if (actionLock.current) return;
    actionLock.current = true; setActionError(null);
    try { await action(); }
    catch (error) { setActionError(getApiErrorMessage(error, fallback)); }
    finally { actionLock.current = false; }
  };
  const copyValue = async (value: string, id: string) => {
    try {
      await navigator.clipboard.writeText(value); setCopied(id);
      if (copyTimer.current) clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(null), 2000);
    } catch { toast.error('Не удалось скопировать. Выделите значение и скопируйте вручную.'); }
  };
  const clearSetup = () => { setSetup(null); setCode(''); setShowSecret(false); setActionError(null); setupMfa.reset(); };
  const closeCreate = () => { setCreateOpen(false); setNewKey(null); setKeyName(''); setActionError(null); setCopied(null); createKey.reset(); };
  const account = profile.data;
  const mfaLabel = account ? (account.mfa_enabled ? 'Включена' : 'Не включена') : 'Нет данных';
  const profileFields: [string, string | undefined][] = [
    ['Email', account?.email ?? user?.email], ['ID пользователя', account?.id ?? user?.id],
    ['Роль', account?.role ?? user?.role], ['ID организации', account?.org_id ?? user?.org_id],
    ['Аккаунт создан', formatDate(account?.created_at)], ['Последний вход', formatDate(account?.last_login_at)],
  ];
  const confirmationBlocked = busy || (confirmation?.kind === 'mfa' ? !canChangeMfa : keys.isError || !keys.isSuccess);

  return <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-background p-4 sm:p-6 lg:p-8">
    <div className="mx-auto w-full max-w-6xl space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div><p className="text-xs font-medium uppercase tracking-widest text-muted-foreground">Аккаунт и доступ</p><h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Настройки</h1><p className="mt-2 max-w-2xl text-sm text-muted-foreground">Профиль, защита входа и ключи интеграций. Права и изменения проверяет сервер.</p></div>
        <Button variant="outline" disabled={profile.isFetching || busy} onClick={() => { void profile.refetch(); }}><RefreshCw className={`mr-2 h-4 w-4 ${profile.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />Обновить профиль</Button>
      </header>
      {profile.isError && <ErrorNotice message={getApiErrorMessage(profile.error, 'Не удалось обновить профиль. Статус защиты сейчас не подтверждён.')}>
        {account && <span className="text-xs text-muted-foreground">Показан последний успешный ответ</span>}
      </ErrorNotice>}
      <section aria-label="Сводка аккаунта" className="grid gap-3 sm:grid-cols-3">
        {[
          { title: 'Пользователь', value: account?.email ?? user?.email ?? 'Нет данных', note: account ? 'Профиль из API' : 'Текущая сессия браузера', icon: UserRound },
          { title: 'Защита входа · MFA', value: mfaLabel, note: profile.isError ? 'Обновление не подтверждено' : 'TOTP-аутентификатор', icon: ShieldCheck },
          { title: 'Организация', value: account?.org_id ?? user?.org_id ?? 'Нет данных', note: 'API-ключи действуют в этой организации', icon: KeyRound },
        ].map(({ title, value, note, icon: Icon }) => <div key={title} className="min-w-0 rounded-xl border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-2 text-sm text-muted-foreground"><span>{title}</span><Icon className="h-4 w-4 shrink-0" aria-hidden="true" /></div><p className="mt-2 break-all text-base font-semibold">{value}</p><p className="mt-1 text-xs text-muted-foreground">{note}</p>
        </div>)}
      </section>
      <Tabs value={tab} onValueChange={(value) => { if (!busy) { if (value !== 'mfa') clearSetup(); setTab(value as TabId); setActionError(null); } }}>
        <TabsList aria-label="Разделы настроек" className="mb-5 h-auto w-full justify-start gap-1 overflow-x-auto rounded-lg p-1 sm:w-auto">
          <TabsTrigger value="profile" disabled={busy} className="flex-1 gap-1 px-2 text-xs sm:flex-none sm:gap-2 sm:px-3 sm:text-sm"><UserRound className="hidden h-4 w-4 sm:block" aria-hidden="true" />Профиль</TabsTrigger>
          <TabsTrigger value="mfa" disabled={busy} className="flex-1 gap-1 px-2 text-xs sm:flex-none sm:gap-2 sm:px-3 sm:text-sm"><ShieldCheck className="hidden h-4 w-4 sm:block" aria-hidden="true" />Безопасность</TabsTrigger>
          <TabsTrigger value="apikeys" disabled={busy} className="flex-1 gap-1 px-2 text-xs sm:flex-none sm:gap-2 sm:px-3 sm:text-sm"><KeyRound className="hidden h-4 w-4 sm:block" aria-hidden="true" />API-ключи</TabsTrigger>
        </TabsList>
        <TabsContent value="profile" className="mt-0 space-y-5">
          <Section title="Профиль пользователя" description="Идентификаторы и время последнего входа из серверного профиля. Это не время создания текущей сессии.">
            {profile.isLoading && <p role="status" className="text-sm text-muted-foreground">Загрузка профиля…</p>}
            <dl className="divide-y divide-border">{profileFields.map(([label, value]) => <div key={label} className="grid gap-1 py-3 first:pt-0 last:pb-0 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
              <dt className="text-sm text-muted-foreground">{label}</dt><dd className="flex min-w-0 items-start justify-between gap-3 text-sm"><span className="break-all">{value || 'Нет данных'}</span>
                {value && value !== 'Нет данных' && <Button size="icon" variant="ghost" className="h-7 w-7 shrink-0" aria-label={`Скопировать ${label}`} onClick={() => { void copyValue(value, label); }}>{copied === label ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}</Button>}
              </dd>
            </div>)}</dl>
          </Section>
          <div className="rounded-lg border border-border bg-muted/30 p-4 text-sm text-muted-foreground">Профиль принадлежит текущему пользователю. Ключи интеграций принадлежат организации. Подтверждение email и срок текущей сессии API не предоставляет.</div>
        </TabsContent>
        <TabsContent value="mfa" className="mt-0">
          <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
            <Section title="Двухфакторная аутентификация" description="Дополнительный TOTP-код при входе в ваш аккаунт.">
              {actionError && !confirmation && <div className="mb-5"><ErrorNotice message={actionError} /></div>}
              {!setup && <div className="space-y-5">
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-muted/30 p-4"><div><p className="font-medium">MFA: {mfaLabel.toLowerCase()}</p><p className="mt-1 text-sm text-muted-foreground">{account?.mfa_enabled ? 'Код потребуется при следующем входе.' : 'QR-код должен быть подтверждён шестизначным кодом.'}</p></div><ShieldCheck className="h-6 w-6 text-primary" aria-hidden="true" /></div>
                {account?.mfa_enabled ? <Button variant="outline" disabled={busy || !canChangeMfa} onClick={() => { setActionError(null); setConfirmation({ kind: 'mfa' }); }}>Отключить MFA</Button>
                  : <Button disabled={busy || !canChangeMfa} onClick={() => { void runAction(() => setupMfa.mutateAsync(), 'Не удалось подготовить MFA. Проверьте профиль и соединение.'); }}>{setupMfa.isPending ? 'Подготовка…' : 'Настроить MFA'}</Button>}
              </div>}
              {setup && <div className="space-y-5">
                <p className="text-sm">1. Сканируйте QR-код в приложении-аутентификаторе.</p>
                {/* Authenticated API supplies this PNG; no external image request. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`data:image/png;base64,${setup.qr_code}`} alt="QR-код для настройки MFA" width={192} height={192} className="mx-auto rounded-lg border border-border bg-white" />
                <div><p className="mb-2 text-sm font-medium">Ключ для ручного ввода</p><div className="flex min-w-0 items-center gap-2 rounded-lg border border-border bg-muted/30 p-3"><span className="min-w-0 flex-1 break-all font-mono text-sm">{showSecret ? setup.secret : '••••••••••••••••'}</span><Button size="icon" variant="ghost" aria-label={showSecret ? 'Скрыть секрет MFA' : 'Показать секрет MFA'} onClick={() => setShowSecret(!showSecret)}>{showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</Button><Button size="icon" variant="ghost" aria-label="Скопировать секрет MFA" onClick={() => { void copyValue(setup.secret, 'mfa'); }}><Copy className="h-4 w-4" /></Button></div></div>
                <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); if (code.length === 6 && !busy && canChangeMfa) void runAction(() => verifyMfa.mutateAsync(code), 'Код не подтверждён. Сеанс настройки мог истечь; начните настройку заново.'); }}>
                  <label htmlFor="mfa-code" className="block text-sm font-medium">2. Код из аутентификатора</label><Input id="mfa-code" autoComplete="one-time-code" inputMode="numeric" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="000000" className="max-w-56 font-mono text-lg tracking-widest" /><p className="text-xs text-muted-foreground">QR-код действителен 5 минут. Если время истекло, начните настройку заново.</p>
                  <div className="flex flex-wrap gap-2"><Button type="submit" disabled={code.length !== 6 || busy || !canChangeMfa}>Подтвердить MFA</Button><Button type="button" variant="outline" disabled={busy} onClick={clearSetup}>Отменить настройку</Button></div>
                </form>
              </div>}
            </Section>
            <aside className="rounded-xl border border-border bg-muted/30 p-5 text-sm text-muted-foreground"><h2 className="mb-2 font-semibold text-foreground">Область изменения</h2><p>Настройка касается только вашего входа в Sphere. Разрешения Android и подключение устройств здесь не меняются.</p><p className="mt-3">Не публикуйте QR-код и секрет MFA. Отключение защиты требует подтверждения.</p></aside>
          </div>
        </TabsContent>
        <TabsContent value="apikeys" className="mt-0 space-y-5">
          <Section title="Ключи интеграций" description="Сервер возвращает активные ключи текущей организации. Полный ключ доступен только один раз при создании.">
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-muted-foreground">{keys.data ? `${keys.data.length} в ответе API` : 'Список ещё не подтверждён'}</p><div className="flex flex-wrap gap-2"><Button variant="outline" disabled={keys.isFetching || busy} onClick={() => { void keys.refetch(); }}><RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />Обновить ключи</Button><Button disabled={busy || keys.isError || !keys.isSuccess} onClick={() => { setKeyName(''); setNewKey(null); setActionError(null); setCreateOpen(true); }}><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Создать ключ</Button></div></div>
            {keys.isLoading && <p role="status" className="py-8 text-center text-sm text-muted-foreground">Загрузка API-ключей…</p>}
            {keys.isError && <ErrorNotice message={getApiErrorMessage(keys.error, 'Не удалось загрузить API-ключи. Проверьте соединение и права доступа.')}>
              {keys.data && <span className="text-xs text-muted-foreground">Сохранён последний успешный список</span>}
            </ErrorNotice>}
            {keys.isSuccess && keys.data.length === 0 && <div className="rounded-lg border border-dashed border-border py-10 text-center"><KeyRound className="mx-auto mb-3 h-7 w-7 text-muted-foreground" aria-hidden="true" /><h3 className="font-medium">Активных API-ключей нет</h3><p className="mt-1 text-sm text-muted-foreground">Создайте ключ для нужной интеграции.</p></div>}
            <div className="space-y-3">{keys.data?.map((key) => <article key={key.id} aria-label={`API-ключ ${key.name}`} className="mt-3 min-w-0 rounded-lg border border-border p-4 sm:p-5">
              <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0 flex-1"><h3 className="break-words font-semibold">{key.name}</h3><p className="mt-1 break-all font-mono text-xs text-muted-foreground">{key.key_prefix}••••••••</p></div><Button variant="outline" size="sm" disabled={busy || keys.isError || !key.is_active} onClick={() => { setActionError(null); setConfirmation({ kind: 'key', key }); }} aria-label={`Отозвать ключ ${key.name}`}>Отозвать</Button></div>
              <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">{[['Создан', formatDate(key.created_at)], ['Последнее использование', key.last_used_at ? formatDate(key.last_used_at) : 'Не использовался'], ['Срок действия', key.expires_at ? formatDate(key.expires_at) : 'Без срока в API']].map(([label, value]) => <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1">{value}</dd></div>)}</dl>
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3 text-xs text-muted-foreground"><span>Разрешения:</span>{key.permissions.length ? key.permissions.map((permission) => <span key={permission} className="rounded-md border border-border px-2 py-1 font-mono">{permission}</span>) : <span>Список разрешений пуст</span>}</div>
            </article>)}</div>
          </Section>
        </TabsContent>
      </Tabs>
      <p className="text-xs text-muted-foreground">Ответ профиля: {profile.dataUpdatedAt ? formatDate(new Date(profile.dataUpdatedAt).toISOString()) : 'ещё не получен'} · время браузера, {Intl.DateTimeFormat().resolvedOptions().timeZone}</p>
    </div>
    <Dialog open={createOpen} onOpenChange={(open) => { if (!open && !busy) closeCreate(); }}>
      <DialogContent className="max-h-[90dvh] w-[calc(100%-2rem)] overflow-y-auto rounded-xl">
        <DialogHeader><DialogTitle>{newKey ? 'Ключ создан' : 'Создать API-ключ'}</DialogTitle><DialogDescription>{newKey ? 'Сохраните ключ сейчас. Повторно сервер его не покажет.' : 'Ключ создаётся в текущей организации. Сервер проверит ваши права.'}</DialogDescription></DialogHeader>
        {actionError && <ErrorNotice message={actionError} />}
        {newKey ? <div className="space-y-4"><p className="text-sm font-medium">{newKey.name}</p><div className="rounded-lg border border-border bg-muted/30 p-3"><code className="break-all text-sm">{newKey.raw_key}</code></div><Button variant="outline" className="w-full" onClick={() => { void copyValue(newKey.raw_key, 'new-key'); }}><Copy className="mr-2 h-4 w-4" aria-hidden="true" />{copied === 'new-key' ? 'Скопировано' : 'Скопировать ключ'}</Button><DialogFooter><Button onClick={closeCreate}>Закрыть и скрыть ключ</Button></DialogFooter></div>
          : <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (keyName.trim() && !busy) void runAction(() => createKey.mutateAsync(keyName.trim()), 'Создание не подтверждено. Проверьте список ключей перед повторным запросом.'); }}>
            <div><label htmlFor="key-name" className="mb-2 block text-sm font-medium">Название интеграции</label><Input id="key-name" maxLength={255} value={keyName} onChange={(event) => setKeyName(event.target.value)} placeholder="Например, CI pipeline" disabled={busy} /></div><p className="text-xs text-muted-foreground">Используются серверные значения разрешений и срока по умолчанию. Пустой список разрешений не обозначает полный доступ.</p><DialogFooter className="gap-2"><Button type="button" variant="outline" disabled={busy} onClick={closeCreate}>Отмена</Button><Button type="submit" disabled={busy || !keyName.trim()}>{createKey.isPending ? 'Создание…' : 'Создать'}</Button></DialogFooter>
          </form>}
      </DialogContent>
    </Dialog>
    <Dialog open={Boolean(confirmation)} onOpenChange={(open) => { if (!open && !busy) { setConfirmation(null); setActionError(null); } }}>
      <DialogContent className="w-[calc(100%-2rem)] rounded-xl">
        <DialogHeader><DialogTitle>{confirmation?.kind === 'key' ? 'Отозвать API-ключ?' : 'Отключить MFA?'}</DialogTitle><DialogDescription>{confirmation?.kind === 'key' ? `Интеграция «${confirmation.key.name}» больше не сможет использовать этот ключ. Восстановить его нельзя.` : 'Следующий вход будет без кода аутентификатора. Это изменение касается только вашего аккаунта.'}</DialogDescription></DialogHeader>
        {actionError && <ErrorNotice message={actionError} />}
        <DialogFooter className="gap-2"><Button variant="outline" disabled={busy} onClick={() => { setConfirmation(null); setActionError(null); }}>Отмена</Button><Button variant="destructive" disabled={confirmationBlocked} onClick={() => {
          if (confirmationBlocked) return;
          if (confirmation?.kind === 'key') void runAction(() => revokeKey.mutateAsync(confirmation.key.id), 'Отзыв ключа не подтверждён. Проверьте список перед повтором.');
          if (confirmation?.kind === 'mfa') void runAction(() => disableMfa.mutateAsync(), 'Отключение MFA не подтверждено. Обновите профиль перед повтором.');
        }}>{busy ? 'Сохранение…' : confirmation?.kind === 'key' ? 'Подтвердить отзыв' : 'Подтвердить отключение'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>;
}
