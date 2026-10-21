'use client';

import { useEffect, useRef, useState } from 'react';
import { FileCheck2, ShieldCheck } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/components/ui/button';
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { validSaveReceipt, type ProfileSaveReceipt, type SavedVpnProfile } from './profileTypes';
import { profileFileHints } from './profileFileHints';

type Receipt = {
  schema_version: 1; config_valid: boolean; apply_allowed: false; persisted: false;
  execution_confirmed: false;
  issues: { code: string; line: number | null }[];
  blockers: string[];
};

const issueLabels: Record<string, string> = {
  executable_or_routing_directive_forbidden: 'Команды и ручные изменения маршрутов запрещены',
  unsupported_field_for_protocol_version: 'Поле не поддерживается выбранной версией протокола',
  invalid_field_value: 'Некорректное значение поля',
  duplicate_field: 'Поле повторяется', duplicate_section: 'Секция повторяется',
  unknown_section: 'Неизвестная секция', invalid_entry: 'Некорректная строка',
  invalid_line: 'Недопустимая или слишком длинная строка',
  missing_awg_parameters: 'Не хватает обязательных параметров AWG',
  awg_header_ranges_overlap: 'Диапазоны заголовков AWG пересекаются',
  junk_size_range_inverted: 'Минимальный размер пакета больше максимального',
  header_protection_requires_four_prefixes: 'Header Protection требует S1–S4 не менее 12 байт',
  ipv6_config_conflicts_with_block_policy: 'IPv6 в конфигурации конфликтует с политикой блокировки',
  ipv6_tunnel_address_and_default_route_required: 'Для IPv6 нужны адрес туннеля и маршрут ::/0',
  selected_app_egress_requires_ipv4_default_route: 'Для выбранных приложений нужен маршрут IPv4 по умолчанию',
  ipv4_tunnel_address_required: 'Нужен IPv4-адрес туннеля', config_too_large: 'Конфигурация больше 64 КиБ',
};

export function validProfileReceipt(value: unknown): value is Receipt {
  if (!value || typeof value !== 'object') return false;
  const r = value as Receipt;
  return r.schema_version === 1 && typeof r.config_valid === 'boolean'
    && r.apply_allowed === false && r.persisted === false && r.execution_confirmed === false
    && Array.isArray(r.issues) && r.issues.length <= 64
    && r.issues.every(i => i && typeof i.code === 'string' && i.code.length <= 128
      && (i.line === null || (Number.isInteger(i.line) && i.line > 0)))
    && r.config_valid === (r.issues.length === 0)
    && Array.isArray(r.blockers) && r.blockers.length > 0 && r.blockers.every(i => typeof i === 'string');
}

/** Raw profile stays in this mounted dialog only, outside query/store caches. */
export function VpnProfileInspector({ onClose, purpose = 'inspect', target, onSaved }: {
  onClose: () => void; purpose?: 'inspect' | 'save'; target?: SavedVpnProfile; onSaved?: () => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const config = useRef<string | null>(null);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const [filename, setFilename] = useState('');
  const [protocol, setProtocol] = useState<'wireguard' | 'amneziawg'>(target?.protocol ?? 'amneziawg');
  const [version, setVersion] = useState(target?.protocol_version ?? '3.1');
  const [packages, setPackages] = useState(target?.traffic_policy.included_packages.join('\n') ?? '');
  const [ipv6, setIpv6] = useState<'block' | 'tunnel'>(target?.traffic_policy.ipv6 ?? 'block');
  const [name, setName] = useState(target?.name ?? '');
  const [description, setDescription] = useState(target?.description ?? '');
  const [saved, setSaved] = useState<ProfileSaveReceipt | null>(null);
  const [unknownRequest, setUnknownRequest] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [fileHint, setFileHint] = useState<ReturnType<typeof profileFileHints>>(null);
  const [pending, setPending] = useState(false);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const initialScope = useRef(useAuthStore.getState().sessionVersion);
  const currentSession = useAuthStore(s => s.sessionVersion);

  useEffect(() => () => { generation.current++; config.current = null; controller.current?.abort(); }, []);
  useEffect(() => {
    if (currentSession !== initialScope.current) { generation.current++; config.current = null; controller.current?.abort(); onClose(); }
  }, [currentSession, onClose]);

  function invalidate() { setReceipt(null); setSaved(null); setError(null); }
  async function readFile(file: File | undefined) {
    const id = ++generation.current;
    config.current = null; setLoaded(false); setFilename(''); setFileHint(null); invalidate();
    if (!file) return;
    if (file.size < 1 || file.size > 65536) { setError('Выбери .conf размером до 64 КиБ.'); return; }
    try {
      const text = await file.text();
      if (id !== generation.current) return;
      config.current = text; setFilename(file.name); setLoaded(true);
      const hint = profileFileHints(text); setFileHint(hint);
      if (hint && !target) {
        setProtocol(hint.protocol);
        setIpv6(hint.ipv6);
      }
    } catch { if (id === generation.current) setError('Не удалось прочитать файл.'); }
  }

  async function inspect() {
    if (!config.current || controller.current || unknownRequest || useAuthStore.getState().sessionVersion !== initialScope.current) return;
    const included = packages.split(/[\s,;]+/).filter(Boolean);
    if (!included.length) { setError('Укажи package ID приложений для VPN.'); return; }
    const id = ++generation.current;
    const abort = new AbortController(); controller.current = abort;
    setPending(true); invalidate();
    let requestId: string | null = null;
    try {
      const profile = {
        schema_version: 1, provider_id: target?.provider_id ?? 'android-amneziawg', protocol,
        protocol_version: protocol === 'wireguard' ? '1' : version,
        config_text: config.current,
        traffic_policy: { mode: 'selected_apps', included_packages: included, control_plane: 'bypass', kill_switch: 'selected_apps', ipv6 },
      };
      if (purpose === 'save') {
        requestId = crypto.randomUUID();
        const path = target ? `/vpn/profiles/${target.id}/revisions` : '/vpn/profiles';
        const { data } = await api.post(path, { request_id: requestId, name, description, profile,
          ...(target ? { expected_revision: target.current_revision } : {}) }, { signal: abort.signal });
        if (id !== generation.current || useAuthStore.getState().sessionVersion !== initialScope.current) return;
        if (!validSaveReceipt(data, requestId, target)) throw new Error('invalid_save_receipt');
        setSaved(data); onSaved?.();
        return;
      }
      const { data } = await api.post('/vpn/profile-preflight', profile, { signal: abort.signal });
      if (id !== generation.current || useAuthStore.getState().sessionVersion !== initialScope.current) return;
      if (!validProfileReceipt(data)) throw new Error('invalid_receipt');
      setReceipt(data);
    } catch (failure) {
      if (id === generation.current && !abort.signal.aborted) {
        const status = (failure as { response?: { status?: number } })?.response?.status;
        if (purpose === 'save' && requestId && ![401, 403, 404, 409, 413, 422].includes(status ?? 0)) {
          setUnknownRequest(requestId);
          setError('Результат сохранения неизвестен. Проверь статус этого запроса; новый импорт автоматически не запускается.');
        } else if (purpose === 'save') setError(status === 409 ? 'Профиль уже изменён или архивирован. Закрой окно и обнови каталог.' : 'Профиль не сохранён. Проверь файл, название, приложения и доступ к каталогу.');
        else setError('Проверка не выполнена. Проверь package ID, доступ к VPN и доступность API проверки профилей.');
      }
    } finally {
      // No secret/config in a mutation cache, localStorage or diagnostic error.
      config.current = null;
      if (controller.current === abort) controller.current = null;
      if (id === generation.current) {
        setPending(false); setLoaded(false);
        if (fileInput.current) fileInput.current.value = '';
      }
    }
  }

  async function checkImport() {
    if (!unknownRequest || controller.current) return;
    const id = ++generation.current;
    const abort = new AbortController(); controller.current = abort; setPending(true);
    try {
      const { data } = await api.get(`/vpn/profiles/imports/${unknownRequest}`, { signal: abort.signal });
      if (id !== generation.current || useAuthStore.getState().sessionVersion !== initialScope.current) return;
      if (!validSaveReceipt(data, unknownRequest, target)) throw new Error('invalid_receipt');
      setSaved(data); setUnknownRequest(null); setError(null); onSaved?.();
    } catch {
      if (id === generation.current && !abort.signal.aborted) setError('Подтверждение сохранения пока не получено. Запрос мог ещё выполняться; повтори проверку статуса.');
    } finally { if (controller.current === abort) controller.current = null; if (id === generation.current) setPending(false); }
  }

  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="max-w-2xl" layout="workspace">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2"><FileCheck2 className="h-5 w-5" /> {purpose === 'save' ? (target ? 'Новая версия VPN-профиля' : 'Импорт VPN-профиля') : 'Проверка VPN-профиля'}</DialogTitle>
        <DialogDescription>{purpose === 'save' ? 'Конфигурация сохранится в зашифрованном каталоге. Сохранение не подключает VPN и не меняет сеть устройства.' : 'Проверим формат и политику приложений. Проверка не сохраняет профиль и не меняет сеть устройства.'}</DialogDescription>
      </DialogHeader>
      <DialogBody>
      <div className="flex items-start gap-3 rounded-xl border p-4 text-sm">
        <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
        <p>В VPN включаются только выбранные приложения. Для Sphere, видео и управления задан обход туннеля.</p>
      </div>
      <fieldset disabled={pending || Boolean(unknownRequest)} className="grid min-w-0 gap-4 disabled:opacity-60">
        {purpose === 'save' && <>
          <label className="grid gap-2 text-sm font-medium">Название профиля<input className="rounded-lg border bg-background p-2.5" value={name} maxLength={120} onChange={e => { setName(e.target.value); invalidate(); }} /></label>
          <label className="grid gap-2 text-sm font-medium">Описание<input className="rounded-lg border bg-background p-2.5" value={description} maxLength={1000} onChange={e => { setDescription(e.target.value); invalidate(); }} /></label>
          {target && <p className="text-xs text-muted-foreground">Ожидаемая версия: {target.current_revision}. Предыдущие версии сохранятся.</p>}
        </>}
        <label className="grid gap-2 text-sm font-medium">Файл конфигурации
          <input ref={fileInput} type="file" accept=".conf,text/plain" aria-label="Файл VPN-профиля" className="w-full min-w-0 rounded-lg border p-3 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-2" onChange={e => void readFile(e.target.files?.[0])} />
        </label>
        {fileHint && <p className="rounded-lg bg-muted/40 px-3 py-2 text-xs text-muted-foreground">По структуре файла: {fileHint.protocol === 'wireguard' ? 'WireGuard' : 'AmneziaWG'}{fileHint.ipv6 === 'tunnel' ? ' · IPv6-адрес и маршрут ::/0' : ''}. {fileHint.partialIpv6 ? 'IPv6 настроен частично — проверь адрес и маршрут.' : fileHint.protocol === 'amneziawg' ? 'Версию AWG выбери по данным провайдера.' : 'Параметры можно изменить ниже.'} Окончательную проверку выполнит сервер.</p>}
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="grid gap-2 text-sm font-medium">Протокол
            <select className="rounded-lg border bg-background p-2.5" value={protocol} onChange={e => { setProtocol(e.target.value as typeof protocol); invalidate(); }}>
              <option value="amneziawg">AmneziaWG</option><option value="wireguard">WireGuard</option>
            </select>
          </label>
          {protocol === 'amneziawg' && <label className="grid gap-2 text-sm font-medium">Версия конфигурации AWG
            <select className="rounded-lg border bg-background p-2.5" value={version} onChange={e => { setVersion(e.target.value); invalidate(); }}>
              {['1', '1.5', '2', '3.1'].map(v => <option key={v}>{v}</option>)}
            </select>
          </label>}
        </div>
        <label className="grid gap-2 text-sm font-medium">Приложения через VPN · package ID
          <textarea rows={3} placeholder="org.example.application" autoComplete="off" spellCheck={false} className="w-full resize-y rounded-lg border bg-background p-3 font-mono text-sm" value={packages} onChange={e => { setPackages(e.target.value); invalidate(); }} />
          <span className="text-xs font-normal text-muted-foreground">По одному ID на строку. Sphere добавлять нельзя; пустой список не допускается.</span>
        </label>
        <label className="grid gap-2 text-sm font-medium">IPv6 выбранных приложений
          <select className="rounded-lg border bg-background p-2.5" value={ipv6} onChange={e => { setIpv6(e.target.value as typeof ipv6); invalidate(); }}>
            <option value="block">Блокировать вне туннеля</option><option value="tunnel">Передавать через туннель с IPv6</option>
          </select>
        </label>
      </fieldset>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {unknownRequest && <div className="grid gap-2 rounded-lg border p-3 text-sm"><p className="break-all font-mono text-xs">ID запроса: {unknownRequest}</p><Button disabled={pending} variant="outline" onClick={() => void checkImport()}>Проверить статус сохранения</Button><p className="text-xs text-muted-foreground">Сохрани ID, если закрываешь окно до получения результата.</p></div>}
      {saved && <p role="status" className="rounded-xl border p-4 text-sm">Профиль сохранён · версия {saved.revision}. Ключи зашифрованы. VPN не подключался.</p>}
      {receipt && <div role="status" className="grid gap-3 rounded-xl border p-4 text-sm">
        <p className="font-medium">{receipt.config_valid ? 'Формат профиля прошёл проверку' : 'Профиль требует исправлений'}{filename ? ` · ${filename}` : ''}</p>
        {receipt.issues.length > 0 && <ul className="list-inside list-disc space-y-1">{receipt.issues.map((i, n) => <li key={n}>{i.line ? `Строка ${i.line}: ` : ''}{issueLabels[i.code] ?? (i.code.startsWith('missing_') ? 'Не хватает обязательного поля конфигурации' : 'Некорректная конфигурация')}</li>)}</ul>}
        <p className="text-muted-foreground">Подключение пока недоступно: Android-адаптер WG/AWG проходит отдельную проверку изоляции приложений и восстановления. Успешный разбор файла не подтверждает работающий VPN.</p>
        <p className="text-xs text-muted-foreground">Для новой проверки выбери файл повторно. Ключи не включены в результат.</p>
      </div>}
      </DialogBody>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>Закрыть</Button>
        <Button disabled={pending || Boolean(unknownRequest) || !loaded || !packages.trim() || (purpose === 'save' && !name.trim())} onClick={() => void inspect()}>{pending ? 'Обрабатываем…' : purpose === 'save' ? 'Проверить и сохранить' : 'Проверить профиль'}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
