'use client';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';

type SessionRecord = { session_id: string; opened_at: string; state: 'active' | 'closed' | 'stale';
  browser_samples?: { received_at: string; rendered_frames: number; incoming_fps: number; control_rtt_ms?: number }[];
  browser_summary?: { max_control_rtt_ms?: number; max_decode_errors: number; max_render_errors: number };
  direct_diagnostics?: { profile: string; path: string; presented_frames: number; echo_rtt_p95_ms?: number; reason?: string }[];
  control_events?: { reason?: string; error: string }[] };

export function StreamSessionHistoryPanel({ deviceId }: { deviceId: string }) {
  const sessionVersion = useAuthStore(state => state.sessionVersion);
  const history = useQuery({
    queryKey: ['stream-session-history', deviceId, sessionVersion],
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/devices/${encodeURIComponent(deviceId)}/stream-sessions`, { signal });
      if (data.schema_version !== 1 || data.device_id !== deviceId || data.session_limit !== 10 || !Array.isArray(data.sessions)
        || data.sessions.length > 10) throw Error('invalid_session_history');
      return data.sessions as SessionRecord[];
    }, refetchInterval: 15000, retry: false, gcTime: 0,
  });
  return <details className="mt-3 rounded-lg border border-border p-3 font-sans text-sm">
    <summary className="cursor-pointer font-medium">Последние 10 сеансов · история диагностики</summary>
    <p className="mt-2 text-xs text-muted-foreground">Отдельная запись на каждую вкладку. До 32 KiB на сеанс, хранение до 7 дней. Здесь нет видеозаписи. Метрики браузера сообщены клиентом; RTT контрольных пакетов не измеряет задержку видео.</p>
    {history.isError ? <p className="mt-2 text-destructive">История сейчас недоступна. Это не означает отсутствие ошибок.</p>
      : !history.data ? <p className="mt-2 text-muted-foreground">Загружаем историю…</p>
      : !history.data.length ? <p className="mt-2 text-muted-foreground">Сеансов ещё нет. Сбор начинается при подключении нового просмотра.</p>
      : <ol className="mt-3 space-y-2">{history.data.map(row => {
        const sample = Array.isArray(row.browser_samples) ? row.browser_samples.at(-1) : null;
        const probe = Array.isArray(row.direct_diagnostics) ? row.direct_diagnostics.at(-1) : null;
        const fault = Array.isArray(row.control_events) ? row.control_events.at(-1) : null;
        return <li key={row.session_id} className="rounded-md border border-border bg-background p-2">
          <div className="flex flex-wrap justify-between gap-2 font-medium"><span>{new Date(row.opened_at).toLocaleString('ru-RU')}</span>
            <span>{({ active: 'Активен', closed: 'Завершён', stale: 'Связь с наблюдателем потеряна' })[row.state] ?? 'Состояние неизвестно'}</span></div>
          <div className="mt-1 text-xs text-muted-foreground">{sample ? `${sample.rendered_frames} кадров · вход ${sample.incoming_fps} FPS` : 'Метрики браузера ещё не получены'}
            {row.browser_summary && ` · максимальный RTT управления ${row.browser_summary.max_control_rtt_ms != null ? `${row.browser_summary.max_control_rtt_ms} мс` : 'не измерен'} · ошибок декодирования ${row.browser_summary.max_decode_errors}`}</div>
          {probe && <div className="mt-1 text-xs">Прямой тест: {probe.profile} · {probe.path} · {probe.presented_frames} кадров
            {probe.echo_rtt_p95_ms != null && ` · RTT пакетов p95 ${probe.echo_rtt_p95_ms.toFixed(1)} мс`}{probe.reason && ` · ${probe.reason}`}</div>}
          {fault && <div className="mt-1 break-words text-xs text-muted-foreground">Последний отказ управления: {fault.reason ?? fault.error}</div>}
        </li>;
      })}</ol>}
  </details>;
}
