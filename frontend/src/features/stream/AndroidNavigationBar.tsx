'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, House, Layers, Loader2, Menu, Keyboard } from 'lucide-react';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { useAuthStore } from '@/lib/store';
import { DEVICE_COMMAND_TIMEOUT, interactiveResult } from '@/src/features/devices/interactiveResult';
import { Button } from '@/src/shared/ui/button';

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
function textCommand(text: string): string | null {
  // The installed root `input text` path cannot type arbitrary Unicode.
  // APK shell() rejects these characters even inside POSIX quotes. An
  // apostrophe would need a backslash escape, which that contract also rejects.
  // Reject locally instead of treating a mocked HTTP response as compatibility.
  if (!text || text.length > 1024 || /[^\x20-\x7e]/.test(text)
    || /[;|&$`(){}\\<>!#~']/.test(text) || text.includes('%s')) return null;
  return `input text '${text.replace(/ /g, '%s')}'`;
}
type Receipt = { state: 'idle' } | { state: 'sending'; label: string }
  | { state: 'confirmed'; label: string; elapsedMs: number }
  | { state: 'unknown'; label: string; message: string };
interface CommandSession {
  deviceId: string;
  token: string | null;
  disposed: boolean;
  controller: AbortController | null;
}

export function AndroidNavigationBar({ deviceId, available, isAvailable, extended = false }: {
  deviceId: string;
  available: boolean;
  /** Recheck transport at the action boundary, even before React rerenders. */
  isAvailable: () => boolean;
  extended?: boolean;
}) {
  const { accessToken } = useAuthStore();
  const sessionRef = useRef<CommandSession | null>(null);
  const [receipt, setReceipt] = useState<Receipt>({ state: 'idle' });
  const [draft, setDraft] = useState('');

  useEffect(() => {
    const session: CommandSession = { deviceId, token: accessToken, disposed: false, controller: null };
    sessionRef.current = session;
    setReceipt({ state: 'idle' });
    setDraft('');
    return () => {
      session.disposed = true;
      // Abort stops this HTTP wait; it cannot revoke an already delivered key.
      session.controller?.abort();
      if (sessionRef.current === session) sessionRef.current = null;
    };
  }, [deviceId, accessToken]);

  const sendCommand = async (command: string, label: string, clearDraft = false) => {
    const session = sessionRef.current;
    if (!available || !isAvailable() || !session || session.disposed || session.controller
      || session.deviceId !== deviceId || session.token !== accessToken) return;
    const controller = new AbortController();
    // Lock synchronously: two clicks in one React batch must not send twice.
    session.controller = controller;
    setReceipt({ state: 'sending', label });
    const started = performance.now();
    try {
      // Installed agents already support the acknowledged interactive SHELL
      // contract. Their flat WebSocket `keyevent` message is not supported.
      const { data } = await api.post(`/devices/${encodeURIComponent(deviceId)}/shell`, {
        command,
      }, { signal: controller.signal, timeout: DEVICE_COMMAND_TIMEOUT.shell });
      if (session.disposed || sessionRef.current !== session) return;
      interactiveResult(data, 'output'); // Empty stdout is a valid completion.
      if (clearDraft) setDraft('');
      setReceipt({ state: 'confirmed', label, elapsedMs: Math.round(performance.now() - started) });
    } catch (error) {
      if (session.disposed || sessionRef.current !== session) return;
      setReceipt({ state: 'unknown', label, message: getApiErrorMessage(
        error, error instanceof Error ? error.message : 'Нет подтверждённого результата команды.',
      ).slice(0, 500) });
    } finally {
      if (!session.disposed && sessionRef.current === session) session.controller = null;
    }
  };
  const sendKey = (key: Pick<AndroidKey, 'code' | 'label'> | (typeof EDIT_KEYS)[number]) => sendCommand(`input keyevent ${key.code}`, key.label);

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
        <Button type="button" disabled={!available || pending || !textCommand(draft)} onClick={() => { const command = textCommand(draft); if (command) void sendCommand(command, 'Ввод текста', true); }}>Ввести текст</Button>
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
    <p role={receipt.state === 'unknown' ? 'alert' : 'status'} aria-live="polite"
      className={`break-words text-xs leading-5 ${receipt.state === 'unknown' ? 'text-destructive' : 'text-muted-foreground'}`}>
      {receipt.state === 'sending' ? `«${receipt.label}»: ожидаем ответ Android…`
        : receipt.state === 'confirmed' ? `«${receipt.label}»: выполнение подтверждено · ответ команды ${receipt.elapsedMs} мс. Это не задержка появления кадра.`
        : receipt.state === 'unknown' ? `«${receipt.label}»: результат не подтверждён. ${receipt.message} Автоповтора нет; проверьте экран перед новым нажатием.`
        : available ? 'Клавиши работают и на неподвижном экране. Действие «Меню» зависит от приложения Android.'
        : 'Навигация доступна после первого видеокадра при активной связи без ошибки управления.'}
    </p>
  </section>;
}
