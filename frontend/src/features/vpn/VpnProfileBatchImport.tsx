'use client';

import { useEffect, useRef, useState } from 'react';
import { Files, ShieldCheck, Upload } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/components/ui/button';
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { profileFileHints } from './profileFileHints';
import { profileIssueLabel } from './profileIssues';
import { parseBatchCheck, parseBatchSaved, parseBatchStatus, type BatchCheck, type BatchItem } from './profileBatchTypes';

type Source = BatchItem & { text: string; protocol: 'wireguard' | 'amneziawg'; ipv6: 'block' | 'tunnel' };
type Phase = 'empty' | 'ready' | 'checked' | 'unknown' | 'saved' | 'rejected';
const field = 'min-w-0 rounded-xl border bg-background p-2.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/** Files/configs live only in this dialog's private ref, never a query/store cache. */
export function VpnProfileBatchImport({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const sources = useRef<Source[]>([]); const input = useRef<HTMLInputElement>(null);
  const generation = useRef(0); const controller = useRef<AbortController | null>(null);
  const scope = useRef(useAuthStore.getState().sessionVersion);
  const session = useAuthStore(s => s.sessionVersion);
  const [items, setItems] = useState<BatchItem[]>([]); const [checks, setChecks] = useState<BatchCheck[]>([]);
  const [phase, setPhase] = useState<Phase>('empty'); const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null); const [packages, setPackages] = useState('');
  const [version, setVersion] = useState('3.1'); const [observed, setObserved] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(true);
  const [onlyErrors, setOnlyErrors] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const alive = (id: number) => id === generation.current && useAuthStore.getState().sessionVersion === scope.current;

  useEffect(() => () => { generation.current++; sources.current = []; controller.current?.abort(); }, []);
  useEffect(() => { if (session !== scope.current) { generation.current++; sources.current = []; controller.current?.abort(); onClose(); } }, [session, onClose]);

  function invalidate() { setChecks([]); setOnlyErrors(false); setError(null); setPhase(sources.current.length ? 'ready' : 'empty'); }
  async function readFiles(files: FileList | null) {
    const id = ++generation.current; sources.current = []; setItems([]); setChecks([]); setError(null); setPhase('empty'); setOnlyErrors(false); setSettingsOpen(true);
    if (!files?.length) return;
    const selected = Array.from(files);
    if (selected.length > 100 || selected.some(f => !/\.conf$/i.test(f.name) || f.size < 1 || f.size > 65536)
      || selected.reduce((sum, f) => sum + f.size, 0) > 3 * 1024 * 1024) { setError('Выбери до 100 файлов .conf: каждый до 64 КиБ, вместе до 3 МиБ.'); return; }
    setPending(true);
    try {
      const loaded: Source[] = [];
      // Bounded sequential reads; a selection change invalidates the remaining work.
      for (const file of selected) {
        const text = await file.text(); if (!alive(id)) return;
        const hint = profileFileHints(text);
        if (!hint) throw new Error('invalid_structure');
        loaded.push({ request_id: crypto.randomUUID(), name: file.name.replace(/\.conf$/i, '').trim().slice(0, 120) || 'VPN profile', text, protocol: hint.protocol, ipv6: hint.ipv6 });
      }
      if (new Set(loaded.map(v => v.request_id)).size !== loaded.length) throw new Error('duplicate_request_id');
      sources.current = loaded; setItems(loaded.map(({ request_id, name }) => ({ request_id, name }))); setPhase('ready');
    } catch { if (alive(id)) { sources.current = []; setError('Не удалось прочитать пакет. Каждый файл должен содержать одну конфигурацию WireGuard или AmneziaWG.'); } }
    finally { if (alive(id)) { setPending(false); if (input.current) input.current.value = ''; } }
  }

  function body() {
    const included = packages.split(/[\s,;]+/).filter(Boolean);
    if (!included.length || included.length > 64) throw new Error('packages_required');
    const result = { items: sources.current.map(source => ({ request_id: source.request_id, name: source.name, description: '', profile: {
      schema_version: 1, provider_id: 'android-amneziawg', protocol: source.protocol,
      protocol_version: source.protocol === 'wireguard' ? '1' : version, config_text: source.text,
      traffic_policy: { mode: 'selected_apps', included_packages: included, control_plane: 'bypass', kill_switch: 'selected_apps', ipv6: source.ipv6 },
    } })) };
    if (new TextEncoder().encode(JSON.stringify(result)).byteLength > 4 * 1024 * 1024) throw new Error('body_too_large');
    return result;
  }

  async function submit(save: boolean) {
    if (controller.current || !sources.current.length || phase === 'unknown' || !alive(generation.current)) return;
    let data: ReturnType<typeof body>;
    try { data = body(); } catch { setError('Укажи от 1 до 64 package ID. Размер JSON-пакета должен быть до 4 МиБ.'); return; }
    const id = ++generation.current; const abort = new AbortController(); controller.current = abort;
    setPending(true); setError(null);
    try {
      const response = await api.post(save ? '/vpn/profiles/batch' : '/vpn/profiles/batch/preflight', data, { signal: abort.signal });
      if (!alive(id)) return;
      if (save) { parseBatchSaved(response.data, items); setObserved(items.length); setPhase('saved'); onSaved(); }
      else {
        const report = parseBatchCheck(response.data, items); setChecks(report); setPhase('checked');
        setSettingsOpen(false); setOnlyErrors(report.some(v => !v.config_valid)); bodyRef.current?.scrollTo?.({ top: 0 });
      }
    } catch (failure) {
      if (alive(id) && !abort.signal.aborted) {
        const status = (failure as { response?: { status?: number } })?.response?.status;
        if (save) {
          const rejected = [401, 403, 409, 413, 422].includes(status ?? 0);
          setPhase(rejected ? 'rejected' : 'unknown');
          setError(rejected ? 'Пакет не сохранён. Проверь доступ, конфигурации и конфликты ID. Выбери файлы заново после исправления.' : 'Результат сохранения неизвестен. Проверь статус запросов; повторного импорта автоматически не будет.');
        } else setError('Проверка пакета не выполнена. Проверь package ID, файлы и доступность API.');
      }
    } finally {
      if (save) sources.current = [];
      if (controller.current === abort) controller.current = null;
      if (alive(id)) setPending(false);
    }
  }

  async function recover() {
    if (controller.current || phase !== 'unknown' || !alive(generation.current)) return;
    const id = ++generation.current; const abort = new AbortController(); controller.current = abort; setPending(true);
    try {
      const { data } = await api.post('/vpn/profiles/batch/status', { request_ids: items.map(v => v.request_id) }, { signal: abort.signal });
      if (!alive(id)) return;
      const receipts = parseBatchStatus(data, items); const count = receipts.filter(Boolean).length; setObserved(count);
      if (count === items.length) { setPhase('saved'); setError(null); onSaved(); }
      else setError(`Подтверждено ${count} из ${items.length}. Остальные пока не наблюдаются; это не отмена запроса. Повтори проверку позже.`);
    } catch { if (alive(id) && !abort.signal.aborted) setError('Статусы пока недоступны. Сохранение не повторялось.'); }
    finally { if (controller.current === abort) controller.current = null; if (alive(id)) setPending(false); }
  }

  const frozen = phase === 'unknown' || phase === 'saved';
  const valid = checks.length === items.length && checks.length > 0 && checks.every(v => v.config_valid);
  const failures = checks.filter(v => !v.config_valid).length;
  return <Dialog open onOpenChange={open => { if (!open && !pending && phase !== 'unknown') onClose(); }}>
    <DialogContent layout="workspace" className="max-w-4xl" onEscapeKeyDown={e => { if (pending || phase === 'unknown') e.preventDefault(); }} onInteractOutside={e => { if (pending || phase === 'unknown') e.preventDefault(); }}>
      <DialogHeader><DialogTitle className="flex items-center gap-3"><span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border bg-primary/10 text-primary"><Files className="h-5 w-5" /></span>Массовый импорт профилей</DialogTitle><DialogDescription>До 100 конфигураций за один проход. Сначала проверка каждого файла, затем сохранение всего пакета одной транзакцией.</DialogDescription></DialogHeader>
      <DialogBody ref={bodyRef}>
        <div className="flex items-start gap-3 rounded-xl border border-primary/15 bg-primary/5 p-4 text-sm"><ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-primary" /><p>Ключи попадут в зашифрованный каталог. Сохранение профилей не назначает VPN устройствам.</p></div>
        {!settingsOpen && <div className="flex items-center justify-between gap-3 rounded-xl border bg-muted/20 p-3"><p className="text-xs leading-relaxed text-muted-foreground">Файлов: {items.length} · приложений: {packages.split(/[\s,;]+/).filter(Boolean).length}<span className="mt-1 block">WG / AWG {version} · Sphere вне VPN</span></p><Button size="sm" variant="outline" disabled={pending || frozen} onClick={() => setSettingsOpen(true)}>Параметры пакета</Button></div>}
        <fieldset hidden={!settingsOpen} disabled={pending || frozen} className={`${settingsOpen ? 'grid' : 'hidden'} min-w-0 gap-4 sm:grid-cols-2 disabled:opacity-60`}>
          <label className="relative col-span-full flex min-h-28 cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed bg-muted/15 p-4 text-center focus-within:ring-2 focus-within:ring-ring"><Upload className="h-5 w-5 text-primary" /><span className="text-sm font-medium">Выбрать несколько файлов .conf</span><span className="text-xs text-muted-foreground">До 64 КиБ каждый · до 3 МиБ вместе</span><input ref={input} aria-label="Файлы VPN-профилей" type="file" accept=".conf" multiple className="absolute inset-0 h-full w-full cursor-pointer opacity-0" onChange={e => void readFiles(e.target.files)} /></label>
          <label className="grid gap-2 text-sm font-medium">Приложения через VPN<textarea rows={3} className={field} value={packages} maxLength={16400} placeholder="org.example.application" onChange={e => { setPackages(e.target.value); invalidate(); }} /><span className="text-xs font-normal text-muted-foreground">Общая политика для пакета. По одному package ID на строку.</span></label>
          <label className="grid content-start gap-2 text-sm font-medium">Версия AmneziaWG<select className={field} value={version} onChange={e => { setVersion(e.target.value); invalidate(); }}><option value="3.1">3.1</option><option value="2">2.0</option><option value="1.5">1.5</option><option value="1">1.0</option></select><span className="text-xs font-normal leading-relaxed text-muted-foreground">WG определяется по структуре файла. Версию AWG укажи по данным провайдера. IPv6 проверяется отдельно для каждого файла.</span></label>
        </fieldset>
        {items.length > 0 && <div className="overflow-hidden rounded-xl border"><div className="flex flex-wrap items-center justify-between gap-2 bg-muted/25 px-4 py-3 text-xs text-muted-foreground"><span>Выбрано {items.length}</span><span>{phase === 'saved' ? `Сохранено ${observed}` : `Проверено ${checks.length}${checks.length ? ` · ошибок ${failures}` : ''}`}</span>{failures > 0 && <Button size="sm" variant="outline" onClick={() => setOnlyErrors(v => !v)}>{onlyErrors ? 'Все профили' : 'Только ошибки'}</Button>}</div><ol aria-label="Результаты проверки пакета" className={`${settingsOpen ? 'max-h-72' : 'max-h-[min(55dvh,32rem)]'} divide-y overflow-y-auto`}>{items.map((item, i) => ({ item, i })).filter(({ i }) => !onlyErrors || checks[i]?.config_valid === false).map(({ item, i }) => <li key={item.request_id} className="flex min-w-0 items-start gap-3 px-4 py-3 text-sm"><span className="w-6 shrink-0 text-xs text-muted-foreground">{i + 1}</span><div className="min-w-0 flex-1"><p className="break-words font-medium">{item.name}</p>{checks[i]?.issues.map((issue, n) => <p key={n} className="mt-1 text-xs text-destructive">{profileIssueLabel(issue.code)}{issue.line ? ` · строка ${issue.line}` : ''}</p>)}</div><span className="shrink-0 text-xs text-muted-foreground">{phase === 'saved' ? 'Сохранён' : checks[i] ? checks[i].config_valid ? 'Проверен' : 'Ошибка' : 'Ожидает'}</span></li>)}</ol></div>}
        {error && <p role="alert" className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 text-sm leading-relaxed text-destructive">{error}</p>}
        {phase === 'saved' && <p role="status" className="text-sm text-success">Сохранено профилей: {observed}. VPN на устройствах не изменялся.</p>}
        {phase === 'unknown' && <details className="rounded-xl border p-3 text-xs"><summary className="cursor-pointer">ID запросов для восстановления результата</summary><pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap break-all">{items.map(v => v.request_id).join('\n')}</pre></details>}
      </DialogBody>
      <DialogFooter className="flex-wrap"><Button variant="outline" disabled={pending} onClick={onClose}>{phase === 'unknown' ? 'Закрыть без повторного импорта' : 'Закрыть'}</Button>{phase === 'unknown' ? <Button disabled={pending} onClick={() => void recover()}>Проверить статус пакета</Button> : phase !== 'saved' && <><Button variant="outline" disabled={pending || !sources.current.length} onClick={() => void submit(false)}>{pending ? 'Обрабатываем…' : 'Проверить пакет'}</Button><Button disabled={pending || !valid || phase !== 'checked'} onClick={() => void submit(true)}>Сохранить {items.length || ''} профилей</Button></>}</DialogFooter>
    </DialogContent>
  </Dialog>;
}
