'use client';
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { installEvidence, isOtaDevice, parseRecoveryStatus, recoveryError, verifyCreatedGrant, type OtaDevice, type OtaRelease } from './recovery';

const time = (value: string | number | null | undefined) => value == null ? 'Не сообщено' : new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString('ru-RU', { timeZone: 'UTC', hour12: false }) + ' UTC';
const stateLabel = { none: 'Разрешения нет', active: 'Ожидается результат Android', expired: 'Срок разрешения истёк', invalid: 'Разрешение не прошло проверку сервера', completed: 'Получен результат установки', failed: 'Установка завершилась ошибкой' };
export function RecoveryDialog({ release, scope, canManage, available, onClose }: {
  release: OtaRelease; scope: string; canManage: boolean; available: boolean; onClose: () => void;
}) {
  const [draft, setDraft] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const devices = useQuery({
    queryKey: ['ota-targets', scope, page, search],
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/devices', { params: { page, per_page: 50, search: search || undefined }, signal });
      if (!data || !Array.isArray(data.items) || !data.items.every(isOtaDevice) || data.page !== page || data.per_page !== 50
        || !Number.isInteger(data.total) || data.total < 0 || !Number.isInteger(data.pages) || data.pages < 0) throw new Error('Invalid device catalog');
      return data as { items: OtaDevice[]; total: number; pages: number };
    }, refetchInterval: 30_000, refetchIntervalInBackground: false,
  });
  return <Dialog open onOpenChange={(open) => { if (!open && !pending) onClose(); }}>
    <DialogContent className="sm:max-w-[980px]" onEscapeKeyDown={(event) => { if (pending) event.preventDefault(); }} onPointerDownOutside={(event) => { if (pending) event.preventDefault(); }}>
      <DialogHeader><DialogTitle>Адресное обновление Android</DialogTitle><DialogDescription>Один опубликованный APK → одно устройство → ограниченное разрешение → результат установки и новый heartbeat. Канал обычных обновлений сохраняется.</DialogDescription></DialogHeader>
      <div className="rounded-lg border bg-muted/30 p-3 text-sm"><p className="font-medium">{release.version_name} · {release.version_code} · {release.platform}/{release.flavor}</p><p className="mt-1 break-all font-mono text-xs">SHA-256: {release.sha256}</p><p className="mt-2 text-xs text-muted-foreground">Пакет и сертификат APK не предоставлены каталогом. Сверьте их совместимость с установленным приложением до выдачи разрешения. Android проверит подпись при установке.</p></div>
      {!available && <p role="alert" className="text-sm text-destructive">Каталог релизов изменился или недоступен. Запись заблокирована до повторной проверки.</p>}
      <div className="grid min-w-0 gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
        <section className="min-w-0 space-y-3" aria-label="Выбор устройства OTA">
          <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); setSearch(draft.trim()); setPage(1); }}>
            <Input aria-label="Поиск устройства OTA" value={draft} maxLength={255} disabled={pending} onChange={(event) => setDraft(event.target.value)} placeholder="Имя, модель или UUID" />
            <Button type="submit" variant="outline" disabled={pending}>Найти</Button>
          </form>
          {devices.isError ? <div role="alert" className="space-y-2 text-sm"><p>Не удалось загрузить устройства.</p><Button variant="outline" onClick={() => { void devices.refetch(); }}>Повторить каталог</Button></div> : devices.isPending ? <p role="status" className="text-sm">Загрузка устройств…</p> : <>
            <p className="text-xs text-muted-foreground">{devices.data.total} устройств · страница {page} из {Math.max(1, devices.data.pages)}</p>
            <div className="max-h-80 space-y-1 overflow-y-auto overscroll-contain rounded-lg border p-1">
              {devices.data.items.length === 0 && <p className="p-3 text-sm">Устройств не найдено.</p>}
              {devices.data.items.map(device => <button key={device.id} type="button" aria-label={`Выбрать ${device.name}`} aria-pressed={selected === device.id} disabled={pending || !device.is_active} onClick={() => setSelected(device.id)} className="w-full rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-pressed:bg-muted disabled:opacity-50 motion-reduce:transition-none"><span className="block font-medium">{device.name}</span><span className="block text-xs text-muted-foreground">{device.status} · {device.agent_version ?? 'Версия не сообщена'}</span></button>)}
            </div>
            <div className="flex items-center justify-between"><Button variant="outline" size="sm" aria-label="Предыдущие устройства" disabled={pending || devices.isFetching || page <= 1} onClick={() => setPage(value => value - 1)}>Назад</Button><Button variant="outline" size="sm" aria-label="Следующие устройства" disabled={pending || devices.isFetching || page >= devices.data.pages} onClick={() => setPage(value => value + 1)}>Далее</Button></div>
          </>}
        </section>
        {selected ? <RecoveryTarget key={selected} deviceId={selected} release={release} scope={scope} canManage={canManage} available={available} setParentPending={setPending} /> : <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">Выберите устройство. Чтение состояния не отправляет команды Android.</p>}
      </div>
      <div className="flex justify-end"><Button variant="outline" disabled={pending} onClick={onClose}>Закрыть</Button></div>
    </DialogContent>
  </Dialog>;
}

function RecoveryTarget({ deviceId, release, scope, canManage, available, setParentPending }: {
  deviceId: string; release: OtaRelease; scope: string; canManage: boolean; available: boolean; setParentPending: (value: boolean) => void;
}) {
  const [duration, setDuration] = useState(600);
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [revokeConfirm, setRevokeConfirm] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const live = useRef(true);
  const busy = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const device = useQuery({ queryKey: ['ota-device', scope, deviceId], queryFn: async ({ signal }) => {
    const { data } = await api.get('/devices/' + deviceId, { signal });
    if (!isOtaDevice(data) || data.id !== deviceId) throw new Error('Invalid device');
    return data;
  }, refetchInterval: 10_000, refetchIntervalInBackground: false });
  const recovery = useQuery({ queryKey: ['ota-recovery', scope, deviceId], queryFn: async ({ signal }) => {
    const { data } = await api.get('/updates/recovery/' + deviceId, { signal });
    return parseRecoveryStatus(data, deviceId);
  }, refetchInterval: 10_000, refetchIntervalInBackground: false });
  const valid = available && Boolean(device.data?.is_active && recovery.data) && !device.isError && !recovery.isError
    && !device.isFetching && !recovery.isFetching && !unknown;
  const active = recovery.data?.active;
  const grantActive = recovery.data?.state === 'active' && active && active.expires_at * 1000 > Date.now();
  const version = device.data?.agent_version_code;
  const canGrant = valid && canManage && !grantActive && recovery.data?.state !== 'invalid'
    && (version == null || version < release.version_code);
  const evidence = device.data && recovery.data && !device.isError && !recovery.isError ? installEvidence(device.data, recovery.data, release) : 'none';

  async function refresh() {
    setRevokeConfirm(false);
    const [d, r] = await Promise.all([device.refetch(), recovery.refetch()]);
    if (live.current && !d.isError && !r.isError) { setUnknown(false); setError(null); }
  }
  async function perform(kind: 'create' | 'dispatch' | 'revoke') {
    if (busy.current || !valid || !canManage || (kind === 'create' ? !canGrant || !consent : !grantActive)) return;
    if (kind === 'dispatch' && (!active || active.expires_at * 1000 <= Date.now())) return;
    const captured = active?.command_id;
    busy.current = true; setPending(true); setParentPending(true); setNotice(null); setError(null);
    try {
      if (kind === 'create') {
        const response = await api.post('/updates/recovery', { device_id: deviceId, sha256: release.sha256, duration_seconds: duration });
        if (response.status !== 201) throw new Error('Unconfirmed grant');
        verifyCreatedGrant(response.data, deviceId, release, duration);
        if (live.current) { setConsent(false); setNotice('Разрешение сохранено. Публикация сигнала доставки не подтверждает установку. Ожидаем результат Android.'); }
      } else if (kind === 'dispatch') {
        const response = await api.post('/updates/recovery/' + deviceId + '/dispatch', { command_id: captured });
        if (response.status !== 202 || response.data?.device_id !== deviceId || response.data?.command_id !== captured
          || !['wake_published', 'awaiting_connection'].includes(response.data?.delivery_hint)) throw new Error('Unconfirmed dispatch');
        if (live.current) setNotice('Повторный сигнал доставки принят. ID и срок разрешения сохранены; ждём результат Android.');
      } else {
        const response = await api.delete('/updates/recovery/' + deviceId, { params: { command_id: captured } });
        if (response.status !== 204) throw new Error('Unconfirmed revoke');
        if (live.current) setNotice('Разрешение отозвано. История результатов сохранена. Уже начатую установку отзыв не отменяет.');
      }
      if (live.current) { setRevokeConfirm(false); await refresh(); }
    } catch (failure) {
      if (live.current) { setError(recoveryError(failure)); setUnknown(true); }
    } finally {
      busy.current = false;
      if (live.current) { setPending(false); setParentPending(false); }
    }
  }
  return <section className="min-w-0 space-y-3" aria-label="Состояние выбранного устройства OTA">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium">{device.data?.name ?? 'Устройство'}</p><p className="break-all font-mono text-xs text-muted-foreground">{deviceId}</p></div><Button variant="outline" size="sm" disabled={pending || device.isFetching || recovery.isFetching} onClick={() => { void refresh(); }}>Обновить состояние</Button></div>
    {device.isPending && <p role="status" className="text-sm">Загрузка карточки…</p>}
    {device.isError && <p role="alert" className="text-sm text-destructive">Не удалось проверить карточку устройства. Управление заблокировано.</p>}
    {device.data && <div className="grid gap-2 rounded-lg border p-3 text-sm sm:grid-cols-2"><p>Установлено: {device.data.agent_version ?? 'Не сообщено'} · {version ?? '—'}</p><p>Состояние: {device.data.status}</p><p className="sm:col-span-2 text-xs text-muted-foreground">Последний heartbeat: {time(device.data.last_heartbeat)}</p></div>}
    {device.data && !['online', 'busy'].includes(device.data.status) && <p className="rounded-lg bg-amber-500/10 p-3 text-sm">Устройство не в сети. Разрешение ограничено сроком и не гарантирует доставку. Android должен восстановить связь до истечения срока.</p>}
    {recovery.isPending && <p role="status" className="text-sm">Проверка OTA…</p>}
    {recovery.isError && <p role="alert" className="text-sm text-destructive">Не удалось проверить состояние OTA. Старый срез не подтверждает результат; запись заблокирована.</p>}
    {recovery.data && !recovery.isError && <>
      <div className="rounded-lg border p-3 text-sm"><p className="font-medium">{stateLabel[recovery.data.state]}</p><p className="mt-1 text-xs text-muted-foreground">Срез сервера: {time(recovery.data.observed_at)}</p>
        {active && <><p className="mt-2 break-all font-mono text-xs">Команда: {active.command_id}</p><p className="text-xs">Срок: {time(active.expires_at)}</p><p className="text-xs">APK: {active.version_name} · {active.version_code}</p></>}
      </div>
      {evidence === 'different' && <p className="text-sm text-muted-foreground">Результат относится к другому APK. Это не подтверждение выбранного релиза.</p>}
      {evidence === 'waiting' && <p className="rounded-lg bg-amber-500/10 p-3 text-sm">Установка сообщена; ожидаем соответствующую версию и свежий heartbeat после результата.</p>}
      {evidence === 'confirmed' && <p role="status" className="rounded-lg bg-success/10 p-3 text-sm font-medium">Установка и heartbeat подтверждены</p>}
      {evidence === 'failed' && <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm">Android сообщил ошибку: <code>{recovery.data.last_result?.failure_code ?? 'Причина не сообщена'}</code></p>}
      {(recovery.data.last_result || recovery.data.recent_results.length > 0) && <details className="rounded-lg border p-3 text-sm"><summary className="cursor-pointer font-medium">История результатов · {Math.max(recovery.data.recent_results.length, recovery.data.last_result ? 1 : 0)}</summary><div className="mt-3 max-h-52 space-y-3 overflow-y-auto">{(recovery.data.recent_results.length ? recovery.data.recent_results : [recovery.data.last_result!]).map(receipt => <div key={receipt.command_id} className="space-y-1 border-b pb-2 text-xs last:border-0"><p>{receipt.version_name} · {receipt.status} · {receipt.failure_code ?? '—'}</p><p className="break-all font-mono">{receipt.command_id}</p><p className="break-all font-mono">SHA-256: {receipt.sha256}</p><p>Сообщена версия: {receipt.installed_version_code ?? '—'} · {time(receipt.recorded_at)}</p><p>Восстановлено после замены процесса: {receipt.recovered_after_process_restart ? 'Да' : 'Нет'}</p></div>)}</div></details>}
    </>}
    {notice && <p role="status" className="rounded-lg border p-3 text-sm">{notice}</p>}
    {error && <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
    {canManage && <div className="space-y-3 rounded-lg border p-3 text-sm">
      {grantActive ? <><div className="flex flex-wrap gap-2"><Button disabled={pending || !valid} onClick={() => { void perform('dispatch'); }}>Повторить доставку</Button><Button variant="outline" disabled={pending || !valid} onClick={() => setRevokeConfirm(true)}>Отозвать разрешение</Button></div>{revokeConfirm && <div role="group" aria-label="Подтверждение отзыва OTA" className="space-y-2 rounded-md bg-destructive/5 p-3"><p className="break-all">Отозвать команду {active?.command_id} для {device.data?.name}? История сохранится; начатая установка может завершиться.</p><div className="flex gap-2"><Button variant="destructive" disabled={pending || !valid} onClick={() => { void perform('revoke'); }}>Подтвердить отзыв</Button><Button variant="outline" disabled={pending} onClick={() => setRevokeConfirm(false)}>Отмена отзыва</Button></div></div>}</> : <>
        <Label htmlFor="ota-duration">Срок разрешения</Label><select id="ota-duration" className="h-10 w-full rounded-md border bg-background px-3" value={duration} disabled={pending} onChange={(event) => setDuration(Number(event.target.value))}><option value={600}>10 минут</option><option value={1800}>30 минут</option><option value={3600}>60 минут</option></select>
        <label className="flex items-start gap-2"><input type="checkbox" className="mt-1 h-4 w-4 shrink-0" checked={consent} disabled={pending || !canGrant} onChange={(event) => setConsent(event.target.checked)} /><span>Подтверждаю совместимость пакета, flavor и сертификата. Разрешаю обновить только это устройство выбранным APK.</span></label>
        {version != null && version >= release.version_code && <p className="text-xs text-muted-foreground">Сообщённая версия не ниже целевой. Переустановка и downgrade здесь недоступны.</p>}
        <Button disabled={pending || !canGrant || !consent} onClick={() => { void perform('create'); }}>{pending ? 'Сохраняем…' : 'Разрешить обновление'}</Button>
      </>}
      <p className="text-xs text-muted-foreground">Запись выполняется один раз. Ошибка транспорта требует повторного чтения результата. Сигнал Pub/Sub и статус online сами по себе не доказывают установку.</p>
    </div>}
    {!canManage && <p className="text-sm text-muted-foreground">Просмотр состояния доступен; выдача и отзыв разрешения требуют super_admin.</p>}
  </section>;
}
