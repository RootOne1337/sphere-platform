'use client';
import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { publicationFailure, validateReleaseDraft, verifyReleaseReceipt, type ReleaseDraft, type ReleaseErrors, type ReleaseIntent } from './releasePublication';

const initial: ReleaseDraft = { platform: 'android', flavor: 'enterprise', version_code: '', version_name: '', download_url: '', sha256: '', mandatory: false, changelog: '' };
export function CreateReleaseDialog({ available, onCreated }: { available: boolean; onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(initial);
  const [errors, setErrors] = useState<ReleaseErrors>({});
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [unresolved, setUnresolved] = useState<ReleaseIntent | null>(null);
  const [notice, setNotice] = useState<{ error: boolean; message: string } | null>(null);
  const request = useRef<AbortController | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; request.current?.abort(); }; }, []);
  const begin = () => { const controller = new AbortController(); request.current = controller; setPending(true); return controller; };
  const finish = () => { request.current = null; if (alive.current) setPending(false); };
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (request.current || unresolved || !available || !consent) return;
    const result = validateReleaseDraft(draft);
    setErrors(result.errors);
    if (!result.intent) return;
    const intent = result.intent;
    const controller = begin();
    setNotice(null);
    try {
      const response = await api.post('/updates/', intent, { signal: controller.signal });
      if (!alive.current) return;
      if (response.status !== 201) throw new Error('Unexpected publication status');
      const id = verifyReleaseReceipt(response.data, intent);
      setNotice({ error: false, message: `Релиз сохранён в каталоге: ${id}. Установка на устройства ещё не подтверждена.` });
      setConsent(false);
      onCreated();
    } catch (error) {
      if (!alive.current) return;
      const failure = publicationFailure(error);
      if (failure.unknown) setUnresolved(intent);
      setNotice({ error: true, message: failure.message });
    } finally { finish(); }
  };
  const reconcile = async () => {
    if (request.current || !unresolved) return;
    const intent = unresolved;
    const controller = begin();
    try {
      const response = await api.get('/updates/', { params: { platform: intent.platform, flavor: intent.flavor }, signal: controller.signal });
      if (!alive.current) return;
      const catalog = response.data as { releases?: unknown[]; total?: number };
      if (!Array.isArray(catalog.releases) || catalog.total !== catalog.releases.length) throw new Error('Invalid catalog');
      const matching = catalog.releases.filter(value => {
        try { verifyReleaseReceipt(value, intent); return true; } catch { return false; }
      });
      if (matching.length !== 1) {
        setNotice({ error: true, message: 'Точное сохранение не подтверждено: релиз отсутствует, отличается или неоднозначен. Повтор заблокирован; проверьте канал и серверный журнал.' });
        return;
      }
      const id = verifyReleaseReceipt(matching[0], intent);
      setUnresolved(null);
      setConsent(false);
      setNotice({ error: false, message: `Сохранение подтверждено повторным чтением каталога: ${id}. Это не подтверждение установки.` });
      onCreated();
    } catch {
      if (alive.current) setNotice({ error: true, message: 'Каталог недоступен. Результат остаётся неизвестным; публикация повторно не отправлена.' });
    } finally { finish(); }
  };
  const edit = (field: keyof ReleaseDraft, value: string | boolean) => { setDraft(previous => ({ ...previous, [field]: value })); setConsent(false); setErrors(previous => ({ ...previous, [field]: undefined })); setNotice(null); };
  const frozen = pending || Boolean(unresolved);
  const field = (key: 'version_code' | 'version_name' | 'download_url' | 'sha256' | 'changelog', label: string, maxLength: number) => <div className="space-y-1.5"><Label htmlFor={`release-${key}`}>{label}</Label><Input id={`release-${key}`} inputMode={key === 'version_code' ? 'numeric' : undefined} maxLength={maxLength} value={draft[key]} disabled={frozen} aria-invalid={Boolean(errors[key])} aria-describedby={errors[key] ? `release-${key}-error` : undefined} onChange={event => edit(key, event.target.value)} />{errors[key] && <p id={`release-${key}-error`} className="text-xs text-destructive">{errors[key]}</p>}</div>;
  return <Dialog open={open} onOpenChange={value => { if (!request.current) setOpen(value); }}>
    <DialogTrigger asChild><Button disabled={!available}>+ New Release</Button></DialogTrigger>
    <DialogContent className="sm:max-w-[600px]" onEscapeKeyDown={event => { if (request.current) event.preventDefault(); }} onInteractOutside={event => { if (request.current) event.preventDefault(); }}>
      <DialogHeader><DialogTitle>Публикация APK-релиза</DialogTitle><DialogDescription>Регистрация метаданных. Managed APK должен быть заранее загружен и проверен; внешний файл сервер не загружает.</DialogDescription></DialogHeader>
      <form onSubmit={submit} className="space-y-4" noValidate aria-busy={pending}>
        <div className="grid gap-3 sm:grid-cols-2">{(['platform', 'flavor'] as const).map(key => <div key={key} className="space-y-1.5"><Label htmlFor={`release-${key}`}>{key === 'platform' ? 'Платформа / канал' : 'Flavor'}</Label><select id={`release-${key}`} className="flex h-10 w-full rounded-md border bg-background px-3 text-sm" disabled={frozen} value={draft[key]} onChange={event => edit(key, event.target.value)}>{(key === 'platform' ? ['android', 'android-canary', 'pc'] : ['enterprise', 'dev']).map(value => <option key={value} value={value}>{value}</option>)}</select></div>)}</div>
        <div className="grid gap-3 sm:grid-cols-2">{field('version_code', 'Номер версии (versionCode)', 10)}{field('version_name', 'Имя версии из APK', 128)}</div>
        {field('download_url', 'HTTPS URL или managed-путь', 4096)}{field('sha256', 'SHA-256 APK', 64)}{field('changelog', 'Изменения', 16384)}
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={draft.mandatory} disabled={frozen} onChange={event => edit('mandatory', event.target.checked)} />Обязательное обновление (ограничения Android продолжают действовать)</label>
        <div className="rounded-lg border bg-muted/40 p-3 text-sm"><p>{draft.platform === 'android-canary' ? 'Canary не предлагается обычным Android-агентам. Для него используется адресное OTA.' : `Релиз станет доступен всем агентам канала ${draft.platform}/${draft.flavor} с меньшим versionCode при следующей проверке.`}</p><p className="mt-1 text-muted-foreground">Пакет и текущая подпись должны совпадать с установленным APK. Номер версии в одном канале нельзя публиковать повторно.</p></div>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={consent} disabled={frozen} onChange={event => setConsent(event.target.checked)} />Подтверждаю совместимость APK и область публикации</label>
        {!available && <p role="alert" className="text-sm text-destructive">Актуальный каталог недоступен или обновляется. Дождитесь успешного чтения.</p>}
        {notice && <p role={notice.error ? 'alert' : 'status'} className={`break-words rounded-lg border p-3 text-sm ${notice.error ? 'border-destructive/30 text-destructive' : 'border-emerald-500/30'}`}>{notice.message}</p>}
        {unresolved && <Button type="button" variant="outline" disabled={pending} onClick={() => { void reconcile(); }}>Сверить результат с каталогом</Button>}
        <DialogFooter><Button type="button" variant="outline" disabled={pending} onClick={() => setOpen(false)}>Закрыть окно</Button><Button type="submit" disabled={pending || !consent || !available || Boolean(unresolved)}>{pending ? 'Проверяем…' : 'Опубликовать релиз'}</Button></DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
