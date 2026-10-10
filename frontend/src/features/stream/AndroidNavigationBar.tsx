'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, House, Layers, Loader2, Menu, Keyboard } from 'lucide-react';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { useAuthStore } from '@/lib/store';
import { DEVICE_COMMAND_TIMEOUT, interactiveResult } from '@/src/features/devices/interactiveResult';
import { Button } from '@/src/shared/ui/button';
import { androidTextCommand as textCommand, type AndroidControlCommand, type AcknowledgedControl, type StreamInput } from './controlObservation';
import type { StreamFrameDimensions } from './streamAspectRatio';

const KEYS = [
  { code: 4, label: 'Назад', icon: ArrowLeft },
  { code: 3, label: 'Домой', icon: House },
  { code: 187, label: 'Недавние', icon: Layers },
  { code: 82, label: 'Меню', icon: Menu },
] as const;
type AndroidKey = (typeof KEYS)[number];
const EDIT_KEYS = [
  { code: 67, label: 'Backspace' }, { code: 112, label: 'Delete' },
  { code: 66, label: 'Enter' }, { code: 61, label: 'Tab' },
  { code: 278, label: 'Копировать в Android' },
  { code: 277, label: 'Вырезать в Android' },
  { code: 279, label: 'Вставить в Android' },
] as const;
type Receipt = { state: 'idle' } | { state: 'sending'; label: string }
  | { state: 'confirmed'; label: string; elapsedMs: number }
  | { state: 'not_sent'; label: string; message: string }
  | { state: 'unknown'; label: string; message: string };
interface CommandSession {
  deviceId: string;
  token: string | null;
  disposed: boolean;
  controller: AbortController | null;
  observation: { requestId: string; input: StreamInput; notify: (event: AcknowledgedControl) => void } | null;
}

export function AndroidNavigationBar({ deviceId, available, isAvailable, prepareCommand, extended = false, getFrameDimensions, onControlCommand }: {
  deviceId: string;
  available: boolean;
  /** Recheck transport at the action boundary, even before React rerenders. */
  isAvailable: () => boolean;
  /** Pause continuous input and wait for native release before a discrete command. Never retry unknown input. */
  prepareCommand?: () => ((confirmed: boolean) => void) | Promise<((confirmed: boolean) => void) | null> | null;
  extended?: boolean;
  getFrameDimensions?: () => StreamFrameDimensions | null;
  onControlCommand?: (event: AcknowledgedControl) => void;
}) {
  const { accessToken } = useAuthStore();
  const sessionRef = useRef<CommandSession | null>(null);
  const [receipt, setReceipt] = useState<Receipt>({ state: 'idle' });
  const [draft, setDraft] = useState('');
  const admissionRef = useRef({ available, isAvailable, prepareCommand });
  admissionRef.current = { available, isAvailable, prepareCommand };

  useEffect(() => {
    const session: CommandSession = { deviceId, token: accessToken, disposed: false, controller: null, observation: null };
    sessionRef.current = session;
    setReceipt({ state: 'idle' });
    setDraft('');
    return () => {
      if (session.observation) {
        session.observation.notify({ requestId: session.observation.requestId, input: session.observation.input, phase: 'unknown', completedAt: performance.now() });
        session.observation = null;
      }
      session.disposed = true;
      // Abort stops this HTTP wait; it cannot revoke an already delivered key.
      session.controller?.abort();
      if (sessionRef.current === session) sessionRef.current = null;
    };
  }, [deviceId, accessToken]);

  const sendCommand = async (command: string, label: string, action: AndroidControlCommand, clearDraft = false) => {
    const session = sessionRef.current;
    if (!admissionRef.current.available || !admissionRef.current.isAvailable() || !session || session.disposed || session.controller
      || session.deviceId !== deviceId || session.token !== accessToken) return;
    const controller = new AbortController();
    // Lock synchronously: two clicks in one React batch must not send twice.
    session.controller = controller;
    setReceipt({ state: 'sending', label });
    const started = performance.now();
    let prepared: ((confirmed: boolean) => void) | null = null;
    let confirmed = false;
    let submitted = false;
    try {
      const prepare = admissionRef.current.prepareCommand;
      const admission = prepare?.();
      prepared = admission instanceof Promise ? await admission : admission ?? null;
      if (prepare && !prepared) throw new Error('Касание Android не освобождено или связь изменилась.');
      if (session.disposed || sessionRef.current !== session) return;
      // `available` disables new clicks while the release render is pending.
      // The already admitted command uses the latest transport/permission predicate.
      if (!admissionRef.current.isAvailable()) throw new Error('Управление больше недоступно.');
      const dimensions = getFrameDimensions?.();
      if (onControlCommand && dimensions) {
        // Observers never control command execution or turn an APK success into
        // an apparent failure. Pass copies so a consumer cannot rewrite a reply.
        const observer = onControlCommand;
        const notify = (event: AcknowledgedControl) => {
          try { observer({ ...event, input: { ...event.input, dimensions: { ...event.input.dimensions }, command: { ...event.input.command } } }); } catch { /* Local recording cannot revoke Android input. */ }
        };
        session.observation = { requestId: crypto.randomUUID(), input: { deviceId, at: started, dimensions: { ...dimensions }, command: { ...action } }, notify };
        notify({ requestId: session.observation.requestId, input: session.observation.input, phase: 'submitted' });
      }
      // Installed agents already support the acknowledged interactive SHELL
      // contract. Their flat WebSocket `keyevent` message is not supported.
      submitted = true;
      const { data } = await api.post(`/devices/${encodeURIComponent(deviceId)}/shell`, {
        command,
      }, { signal: controller.signal, timeout: DEVICE_COMMAND_TIMEOUT.shell });
      if (session.disposed || sessionRef.current !== session) return;
      interactiveResult(data, 'output'); // Empty stdout is a valid completion.
      confirmed = true;
      if (session.observation) {
        session.observation.notify({ requestId: session.observation.requestId, input: session.observation.input, phase: 'confirmed', completedAt: performance.now() });
        session.observation = null;
      }
      if (clearDraft) setDraft('');
      setReceipt({ state: 'confirmed', label, elapsedMs: Math.round(performance.now() - started) });
    } catch (error) {
      if (session.disposed || sessionRef.current !== session) return;
      if (session.observation) {
        session.observation.notify({ requestId: session.observation.requestId, input: session.observation.input, phase: 'unknown', completedAt: performance.now() });
        session.observation = null;
      }
      setReceipt({ state: submitted ? 'unknown' : 'not_sent', label, message: getApiErrorMessage(
        error, error instanceof Error ? error.message : 'Нет подтверждённого результата команды.',
      ).slice(0, 500) });
    } finally {
      prepared?.(confirmed || !submitted);
      if (!session.disposed && sessionRef.current === session) session.controller = null;
    }
  };
  const sendKey = (key: Pick<AndroidKey, 'code' | 'label'> | (typeof EDIT_KEYS)[number]) => sendCommand(`input keyevent ${key.code}`, key.label, { type: 'key_event', keycode: key.code });

  const pending = receipt.state === 'sending';
  return <section aria-label="Навигация Android" aria-busy={pending}
    className="shrink-0 space-y-2 border-t border-border bg-card p-3 text-foreground">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-xs font-medium">Навигация Android</span>
      <span className="text-[11px] text-muted-foreground">Через APK · требуется root-доступ</span>
    </div>
    {extended && <details className="rounded-lg border border-border p-3">
      <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium"><Keyboard className="h-4 w-4" aria-hidden />Клавиатура и текст</summary>
      <div className="mt-3 space-y-3">
        <p className="text-xs leading-relaxed text-muted-foreground">Выберите поле на экране Android. Копировать/вырезать/вставить работают с выделением и буфером Android; буфер браузера отдельный. Колесо над видео выполняет короткий свайп; Ctrl + колесо оставляет масштабирование браузера.</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{EDIT_KEYS.map(key => <Button key={key.code} type="button" variant="outline" size="sm" disabled={!available || pending} onClick={() => { void sendKey(key); }}>{key.label}</Button>)}</div>
        <label className="block space-y-2 text-xs font-medium"><span>Текст для Android</span><textarea aria-label="Текст для Android" value={draft} disabled={!available || pending} maxLength={1024} onChange={event => setDraft(event.target.value)} rows={2} className="block w-full resize-y rounded-lg border border-input bg-background p-3 text-sm disabled:opacity-50" /></label>
        <p className="text-xs leading-relaxed text-muted-foreground">До 1024 символов ASCII в пределах ограничений установленного APK. Кириллица, emoji, переносы строк, апостроф, служебные символы shell и буквальная последовательность %s не отправляются. Для них требуется отдельный Android-канал ввода текста.</p>
        {draft && !textCommand(draft) && <p role="alert" className="text-xs text-destructive">Текст содержит символы, которые текущий Android-канал не поддерживает. Команда не отправлена.</p>}
        <Button type="button" disabled={!available || pending || !textCommand(draft)} onClick={() => { const command = textCommand(draft); if (command) void sendCommand(command, 'Ввод текста', { type: 'type_text', text: draft }, true); }}>Ввести текст</Button>
      </div>
    </details>}
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {KEYS.map((key) => <Button key={key.code} type="button" variant="outline"
        disabled={!available || pending} onClick={() => { void sendKey(key); }}>
        {pending && receipt.label === key.label
          ? <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          : <key.icon className="mr-2 h-4 w-4" aria-hidden="true" />}
        {key.label}
      </Button>)}
    </div>
    <p role={receipt.state === 'unknown' || receipt.state === 'not_sent' ? 'alert' : 'status'} aria-live="polite"
      className={`break-words text-xs leading-5 ${receipt.state === 'unknown' || receipt.state === 'not_sent' ? 'text-destructive' : 'text-muted-foreground'}`}>
      {receipt.state === 'sending' ? `«${receipt.label}»: ожидаем ответ Android…`
        : receipt.state === 'confirmed' ? `«${receipt.label}»: выполнение подтверждено · ответ команды ${receipt.elapsedMs} мс. Это не задержка появления кадра.`
        : receipt.state === 'unknown' ? `«${receipt.label}»: результат не подтверждён. ${receipt.message} Автоповтора нет; проверьте экран перед новым нажатием.`
        : receipt.state === 'not_sent' ? `«${receipt.label}»: команда не отправлена. ${receipt.message}`
        : available ? 'Клавиши работают и на неподвижном экране. Действие «Меню» зависит от приложения Android.'
        : 'Навигация доступна после первого видеокадра при активной связи без ошибки управления.'}
    </p>
  </section>;
}
