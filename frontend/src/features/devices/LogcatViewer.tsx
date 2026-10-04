'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { Button } from '@/src/shared/ui/button';
import { DEVICE_COMMAND_TIMEOUT, interactiveResult } from './interactiveResult';

export function LogcatViewer({ deviceId, enabled = true }: { deviceId: string; enabled?: boolean }) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const fetchLogs = useCallback(async () => {
    if (!enabledRef.current || active.current) return;
    const controller = new AbortController(); active.current = controller;
    setLoading(true); setError(null);
    try {
      const { data } = await api.post(`/devices/${encodeURIComponent(deviceId)}/logcat`, { lines: 500, mode: 'sphere' }, { signal: controller.signal, timeout: DEVICE_COMMAND_TIMEOUT.logs });
      const logs = interactiveResult(data, 'logcat');
      if (!controller.signal.aborted) { setContent(logs); setUpdatedAt(new Date().toISOString()); }
    } catch (error) {
      if (!controller.signal.aborted) setError(getApiErrorMessage(error, error instanceof Error ? error.message : 'Не удалось запросить логи APK.'));
    } finally {
      if (!controller.signal.aborted) { setLoading(false); active.current = null; }
    }
  }, [deviceId]);
  useEffect(() => {
    setContent(null); setUpdatedAt(null); setError(null); setLoading(false);
    void fetchLogs();
    return () => { active.current?.abort(); active.current = null; };
  }, [fetchLogs]);
  return <section aria-label="Логи по запросу к APK" className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-card">
    <header className="space-y-2 border-b border-border bg-muted/30 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><h4 className="text-sm font-semibold">Логи Sphere · запрос к APK</h4><Button variant="outline" size="sm" disabled={!enabled || loading} onClick={() => { void fetchLogs(); }}>Запросить снова</Button></div><p className="text-xs text-muted-foreground">До 500 последних строк. Это разовый ответ агента, не непрерывная трансляция системного Logcat.</p>{updatedAt && <p className="text-xs text-muted-foreground">Ответ получен: {updatedAt}</p>}</header>
    <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3">
      {error && <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}{content !== null ? ' Показан предыдущий ответ.' : ''}</p>}
      {loading && <p role="status" className="text-sm text-muted-foreground">Запрос к Android-агенту…</p>}
      {content !== null && <pre aria-label="Ответ логов APK" className="whitespace-pre-wrap break-all font-mono text-xs leading-relaxed">{content || 'APK вернул пустой журнал.'}</pre>}
    </div>
  </section>;
}
