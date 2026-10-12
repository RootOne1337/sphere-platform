'use client';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';

const nativeStageText: Record<string, string> = {
  offer_received: 'APK получил запрос', factory_ready: 'WebRTC подготовлен', peer_ready: 'Соединение создано',
  remote_description_set: 'Параметры браузера приняты', answer_created: 'Ответ APK подготовлен',
  local_description_set: 'Параметры APK установлены', gathering: 'Поиск сетевого пути', gathered: 'Кандидаты собраны',
  answer_sent: 'Ответ APK отправлен', channel_received: 'Канал получен', channel_open: 'Прямой канал открыт',
  remote_description_failed: 'Параметры браузера отклонены', answer_creation_failed: 'Ответ APK не подготовлен',
  local_description_failed: 'Параметры APK не установлены', peer_setup_failed: 'Соединение не подготовлено',
  answer_delivery_failed: 'Ответ APK не отправлен', connection_failed: 'Соединение прервано',
  closed: 'Соединение закрыто', expired: 'Срок подключения истёк',
};

type IceSnapshot = { local_candidates: number; remote_candidates: number; pairs: number;
  checking_pairs: number; failed_pairs: number; succeeded_pairs: number;
  requests_sent: number | null; responses_received: number | null };
type DirectFailureObservation = { reason: string; received_at: string; attempt?: number;
  ice_state?: string; dtls_state?: string; network?: IceSnapshot;
  network_sample_elapsed_ms?: number; network_age_at_stop_ms?: number };
const directFailureText: Record<string, string> = {
  gathering_deadline: 'Не удалось завершить поиск сетевых адресов',
  signaling_deadline: 'Не получен ответ на согласование',
  connection_deadline: 'Прямой сетевой маршрут не установлен в срок',
  peer_disconnected: 'Прямое соединение прервано',
  video_first_frame_timeout: 'Первый прямой видеокадр не получен',
  video_frame_timeout: 'Прямые видеокадры перестали поступать',
  video_access_rejected: 'Доступ к прямому каналу отозван',
  network_changed: 'Сеть браузера изменилась',
};

type SessionRecord = { session_id: string; opened_at: string; state: 'active' | 'closed' | 'stale';
  browser_samples?: { received_at: string; rendered_frames: number; incoming_fps: number; control_rtt_ms?: number;
    control_transport?: 'server_websocket' | 'direct_webrtc';
    transport?: 'server_websocket' | 'direct_webrtc'; direct_frames?: number; direct_fps?: number | null;
    direct_path?: string; direct_network_rtt_ms?: number | null; direct_jitter_buffer_ms?: number | null;
    direct_decode_ms?: number | null; direct_state?: string | null; direct_failure?: string | null;
    direct_ice_state?: string | null; direct_dtls_state?: string | null;
    direct_network?: IceSnapshot | null }[];
  browser_summary?: { max_control_rtt_ms?: number; max_decode_errors: number; max_render_errors: number;
    last_direct_failure?: DirectFailureObservation;
    last_control_failure_detail?: string; last_control_fence_received_at?: string;
    last_control_fence?: {phase:string;pointer_held:boolean;idle_heartbeat_only:boolean;pending_count:number|null;
      oldest_age_ms:number|null;last_receipt_rtt_ms:number|null;tick_gap_ms:number|null;buffered_bytes:number|null} };
  direct_diagnostics?: { profile: string; path: string; presented_frames: number; echo_rtt_p95_ms?: number; reason?: string }[];
  native_direct_samples?: { received_at: string; peer_id: string; sequence: number; kind: 'sample' | 'final';
    stage: string; elapsed_ms: number; answer_sent: boolean; network_sample_age_ms: number | null;
    network: { local_candidates: number; remote_candidates: number; pairs: number; checking_pairs: number;
      failed_pairs: number; succeeded_pairs: number; requests_sent: number | null; requests_received: number | null;
      responses_sent: number | null; responses_received: number | null; dtls_state: string | null } | null }[];
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
        const lastDirectFailure = row.browser_summary?.last_direct_failure;
        const probe = Array.isArray(row.direct_diagnostics) ? row.direct_diagnostics.at(-1) : null;
        const fault = Array.isArray(row.control_events) ? row.control_events.at(-1) : null;
        const network = sample?.direct_network;
        const native = Array.isArray(row.native_direct_samples) ? row.native_direct_samples.at(-1) : null;
        const nativeNetwork = native?.network;
        return <li key={row.session_id} className="rounded-md border border-border bg-background p-2">
          <div className="flex flex-wrap justify-between gap-2 font-medium"><span>{new Date(row.opened_at).toLocaleString('ru-RU')}</span>
            <span>{({ active: 'Активен', closed: 'Завершён', stale: 'Связь с наблюдателем потеряна' })[row.state] ?? 'Состояние неизвестно'}</span></div>
          <div className="mt-1 text-xs text-muted-foreground">{sample?.transport === 'direct_webrtc'
            ? `Основное видео · WebRTC · ${sample.direct_frames ?? '—'} кадров · ${sample.direct_fps?.toFixed(1) ?? '—'} FPS · путь ${sample.direct_path ?? 'не определён'}`
            : sample ? `Видео через сервер · ${sample.rendered_frames} кадров · вход ${sample.incoming_fps} FPS` : 'Метрики браузера ещё не получены'}
            {row.browser_summary && ` · максимальный RTT управления ${row.browser_summary.max_control_rtt_ms != null ? `${row.browser_summary.max_control_rtt_ms} мс` : 'не измерен'} · ошибок декодирования ${row.browser_summary.max_decode_errors}`}</div>
          {sample?.transport === 'direct_webrtc' && <div className="mt-1 text-xs text-muted-foreground">
            RTT сети {sample.direct_network_rtt_ms?.toFixed(1) ?? '—'} мс · буфер приёма {sample.direct_jitter_buffer_ms?.toFixed(1) ?? '—'} мс · декодирование {sample.direct_decode_ms?.toFixed(1) ?? '—'} мс.
            Это отдельные этапы, а не полная задержка картинки.
          </div>}
          {sample && <div className="mt-1 text-xs text-muted-foreground">{sample.control_transport === 'direct_webrtc'
            ? 'Касания напрямую · WebRTC' : sample.control_transport === 'server_websocket'
              ? 'Касания через сервер · WebSocket' : 'Маршрут касаний не сообщён'}</div>}
          {sample?.direct_state && <div className="mt-1 text-xs text-muted-foreground">Прямой канал: {sample.direct_state}
            {` · ICE ${sample.direct_ice_state ?? '—'} · DTLS ${sample.direct_dtls_state ?? '—'}`}
            {sample.direct_failure && ` · причина ${sample.direct_failure}`}</div>}
          {network && <div className="mt-1 text-xs text-muted-foreground">
            ICE-запросы / ответы: {network.requests_sent ?? '—'} / {network.responses_received ?? '—'}
            {` · проверка / отказ / успех: ${network.checking_pairs} / ${network.failed_pairs} / ${network.succeeded_pairs} из ${network.pairs}`}
            {` · ICE-кандидатов браузера / APK: ${network.local_candidates} / ${network.remote_candidates}`}
          </div>}
          {lastDirectFailure && <details className="mt-2 min-w-0 text-xs text-muted-foreground">
            <summary className="cursor-pointer">Последний отказ прямого канала · {new Date(lastDirectFailure.received_at).toLocaleString('ru-RU')}</summary>
            <p className="mt-1">{directFailureText[lastDirectFailure.reason] ?? 'Прямое соединение завершилось с ошибкой'}.
              {lastDirectFailure.attempt != null && ` Попытка ${lastDirectFailure.attempt}.`}
              {` ICE ${lastDirectFailure.ice_state ?? 'не измерен'} · DTLS ${lastDirectFailure.dtls_state ?? 'не измерен'}.`}</p>
            {lastDirectFailure.network && <p className="mt-1">При отказе · ICE-запросы / ответы: {lastDirectFailure.network.requests_sent ?? '—'} / {lastDirectFailure.network.responses_received ?? '—'}.
              {lastDirectFailure.network.requests_sent != null && lastDirectFailure.network.requests_sent > 0
                && lastDirectFailure.network.responses_received === 0 && ' Запросы отправлялись, ответы не получены; причина ограничения сети этим не установлена.'}</p>}
            <p className="mt-1">Это сохранённый отказ, а не текущее состояние соединения. Код: <code>{lastDirectFailure.reason}</code>.</p>
          </details>}
          {probe && <div className="mt-1 text-xs">Прямой тест: {probe.profile} · {probe.path} · {probe.presented_frames} кадров
            {probe.echo_rtt_p95_ms != null && ` · RTT пакетов p95 ${probe.echo_rtt_p95_ms.toFixed(1)} мс`}{probe.reason && ` · ${probe.reason}`}</div>}
          <details className="mt-2 min-w-0 text-xs text-muted-foreground">
            <summary className="cursor-pointer">Диагностика прямого соединения со стороны APK · {native ? 'получена' : 'нет данных'}</summary>
            {native ? <div className="mt-1 space-y-1">
              <p>Этап: {nativeStageText[native.stage] ?? 'не определён'} · {native.kind === 'final' ? 'итог при закрытии' : 'наблюдение'} · ответ на согласование {native.answer_sent ? 'отправлен APK' : 'ещё не отправлен'}.</p>
              <p>Получено сервером: {new Date(native.received_at).toLocaleString('ru-RU')} · {native.elapsed_ms} мс от начала этой попытки.</p>
              {nativeNetwork ? <>
                <p>APK · ICE-запросы исходящие / входящие: {nativeNetwork.requests_sent ?? '—'} / {nativeNetwork.requests_received ?? '—'} · ответы исходящие / входящие: {nativeNetwork.responses_sent ?? '—'} / {nativeNetwork.responses_received ?? '—'}.</p>
                <p>Проверка / отказ / успех: {nativeNetwork.checking_pairs} / {nativeNetwork.failed_pairs} / {nativeNetwork.succeeded_pairs} из {nativeNetwork.pairs} · DTLS {nativeNetwork.dtls_state ?? '—'}.</p>
                <p>ICE-кандидатов APK / удалённой стороны: {nativeNetwork.local_candidates} / {nativeNetwork.remote_candidates} · с момента запроса getStats до отправки отчёта: {native.network_sample_age_ms ?? '—'} мс.</p>
                <p>Это время запроса статистики, не задержка видео. Внутренний timestamp RTCStats здесь не измерен; getStats может возвращать кэшированные данные.</p>
              </> : <p>Сетевые счётчики APK не получены.</p>}
            </div> : <p className="mt-1">APK не сообщил данные для этой попытки. Отсутствие отчёта не означает нулевые счётчики или исправное соединение.</p>}
          </details>
          {fault && <div className="mt-1 break-words text-xs text-muted-foreground">Последний отказ управления: {fault.reason ?? fault.error}</div>}
          {row.browser_summary?.last_control_failure_detail && <div className="mt-1 break-words text-xs text-muted-foreground">
            Последний сбой в браузере: {row.browser_summary.last_control_failure_detail}.
            {row.browser_summary.last_control_fence && <>
              {` Фаза ${row.browser_summary.last_control_fence.phase} · ${row.browser_summary.last_control_fence.pointer_held ? 'касание удерживалось' : row.browser_summary.last_control_fence.idle_heartbeat_only ? 'только heartbeat без касания' : 'касание не удерживалось'}.`}
              {` Ожидали ACK: ${row.browser_summary.last_control_fence.pending_count ?? '—'} · возраст старейшей команды ${row.browser_summary.last_control_fence.oldest_age_ms ?? '—'} мс · последний RTT ${row.browser_summary.last_control_fence.last_receipt_rtt_ms ?? '—'} мс.`}
              {` Разрыв тиков браузера ${row.browser_summary.last_control_fence.tick_gap_ms ?? '—'} мс · буфер отправки ${row.browser_summary.last_control_fence.buffered_bytes ?? '—'} B.`}
            </>}
          </div>}
        </li>;
      })}</ol>}
  </details>;
}
