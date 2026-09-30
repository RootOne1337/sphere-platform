'use client';

import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, House, Layers, Loader2, Menu } from 'lucide-react';
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
type Receipt = { state: 'idle' } | { state: 'sending'; label: string }
  | { state: 'confirmed'; label: string; elapsedMs: number }
  | { state: 'unknown'; label: string; message: string };
interface CommandSession {
  deviceId: string;
  token: string | null;
  disposed: boolean;
  controller: AbortController | null;
}

export function AndroidNavigationBar({ deviceId, available, isAvailable }: {
  deviceId: string;
  available: boolean;
  /** Recheck transport at the action boundary, even before React rerenders. */
  isAvailable: () => boolean;
}) {
  const { accessToken } = useAuthStore();
  const sessionRef = useRef<CommandSession | null>(null);
  const [receipt, setReceipt] = useState<Receipt>({ state: 'idle' });

  useEffect(() => {
    const session: CommandSession = { deviceId, token: accessToken, disposed: false, controller: null };
    sessionRef.current = session;
    setReceipt({ state: 'idle' });
    return () => {
      session.disposed = true;
      // Abort stops this HTTP wait; it cannot revoke an already delivered key.
      session.controller?.abort();
      if (sessionRef.current === session) sessionRef.current = null;
    };
  }, [deviceId, accessToken]);

  const sendKey = async (key: AndroidKey) => {
    const session = sessionRef.current;
    if (!available || !isAvailable() || !session || session.disposed || session.controller
      || session.deviceId !== deviceId || session.token !== accessToken) return;
    const controller = new AbortController();
    // Lock synchronously: two clicks in one React batch must not send twice.
    session.controller = controller;
    setReceipt({ state: 'sending', label: key.label });
    const started = performance.now();
    try {
      // Installed agents already support the acknowledged interactive SHELL
      // contract. Their flat WebSocket `keyevent` message is not supported.
      const { data } = await api.post(`/devices/${encodeURIComponent(deviceId)}/shell`, {
        command: `input keyevent ${key.code}`,
      }, { signal: controller.signal, timeout: DEVICE_COMMAND_TIMEOUT.shell });
      if (session.disposed || sessionRef.current !== session) return;
      interactiveResult(data, 'output'); // Empty stdout is a valid completion.
      setReceipt({ state: 'confirmed', label: key.label, elapsedMs: Math.round(performance.now() - started) });
    } catch (error) {
      if (session.disposed || sessionRef.current !== session) return;
      setReceipt({ state: 'unknown', label: key.label, message: getApiErrorMessage(
        error, error instanceof Error ? error.message : 'Нет подтверждённого результата команды.',
      ).slice(0, 500) });
    } finally {
      if (!session.disposed && sessionRef.current === session) session.controller = null;
    }
  };

  const pending = receipt.state === 'sending';
  return <section aria-label="Навигация Android" aria-busy={pending}
    className="shrink-0 space-y-2 border-t border-border bg-card p-3 text-foreground">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-xs font-medium">Навигация Android</span>
      <span className="text-[11px] text-muted-foreground">Через APK · требуется root-доступ</span>
    </div>
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
