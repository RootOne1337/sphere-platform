'use client';
import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/lib/store';
import { startDirectProbe, type DirectProbeResult } from './directProbe';
import { DirectProbeConfigurationError } from './directProbeIce';

const phaseText: Record<DirectProbeResult['state'], string> = {
  gathering: 'Подготовка сетевых адресов', signaling: 'Согласование с APK через сервер',
  connecting: 'APK ответил · проверка прямого сетевого пути', connected: 'Канал открыт · выполняется замер',
  finished: '20 замеров завершены', stopped: 'Замер остановлен', failed: 'Соединение не подтверждено',
};
const reasonText: Record<string, string> = {
  gathering_deadline: 'За 8 секунд браузер не завершил сбор ICE-адресов. До проверки пути с APK дело не дошло.',
  signaling_deadline: 'За 8 секунд не получен и не установлен ответ APK. Прямой путь ещё не проверен.',
  connection_deadline: 'За 12 секунд после ответа APK канал не открылся. Это не измерение задержки; нужно проверить сетевой путь.',
  invalid_controlled_stun: 'Диагностический STUN-профиль сборки некорректен. Проверка не запускалась.',
  invalid_ice_grant: 'Сервер не выдал допустимый временный доступ к relay. WebRTC не запускался.',
  probe_deadline: 'Истёк общий срок проверки. Незавершённые замеры не повторяются.',
  echo_timeout: 'Ответ APK на пробный пакет не получен вовремя.',
  signaling_closed: 'Сервер закрыл согласование. Проверьте доступ устройства к эксперименту и актуальность APK.',
  signaling_unavailable: 'Согласование с сервером недоступно.',
  webrtc_unavailable: 'Этот браузер не смог подготовить WebRTC.',
  peer_disconnected: 'Прямой канал прерван.',
};

export type DiagnosticProfile = 'host' | 'public-stun' | 'turn';

export function DirectProbeDiagnostics({ deviceId, profile, onBusyChange }: { deviceId: string; profile?: DiagnosticProfile; onBusyChange?: (busy: boolean) => void }) {
  const token = useAuthStore(state => state.accessToken);
  const [result, setResult] = useState<DirectProbeResult | null>(null);
  const stop = useRef<(() => void) | null>(null);
  const active = result && ['gathering', 'signaling', 'connecting', 'connected'].includes(result.state);
  useEffect(() => { onBusyChange?.(!!active); }, [active, onBusyChange]);
  const relayGrant = profile ? profile === 'turn' : process.env.NEXT_PUBLIC_DIRECT_PROBE_RELAY === 'true';
  const controlledStunUrl = profile ? profile === 'public-stun' ? 'stun:stun.cloudflare.com:3478' : undefined
    : process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL;
  useEffect(() => {
    setResult(null);
    const onHidden = () => { if (document.hidden) { stop.current?.(); stop.current = null; } };
    document.addEventListener('visibilitychange', onHidden);
    return () => { stop.current?.(); stop.current = null; document.removeEventListener('visibilitychange', onHidden); };
  }, [deviceId, token, profile]);
  const begin = () => {
    if (!token) return;
    stop.current?.();
    try {
      const base = process.env.NEXT_PUBLIC_WS_URL ?? `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;
      stop.current = startDirectProbe(`${base}/ws/direct-probe/${encodeURIComponent(deviceId)}`, token, setResult,
        { controlledStunUrl, relayGrant });
    } catch (error) { setResult({ state: 'failed', samples: [], path: 'unknown', protocol: null,
      reason: error instanceof DirectProbeConfigurationError ? 'invalid_controlled_stun' : 'webrtc_unavailable' }); }
  };
  const sorted = result ? [...result.samples].sort((a, b) => a - b) : [];
  const p95 = sorted.length ? sorted[Math.ceil(sorted.length * .95) - 1].toFixed(1) : null;
  return <section className="mt-3 rounded-lg border border-border bg-background p-3 font-sans" aria-label="Проверка прямого канала WebRTC">
    <div className="font-medium">Прямой канал · экспериментальная проверка</div>
    <p className="mt-1 text-muted-foreground">До 20 замеров между браузером и APK за 30 секунд. Видео и касания пока используют текущий транспорт. {relayGrant
      ? 'Сервер выдаёт временный TURN-доступ. Фактически выбранный путь показан ниже.' : controlledStunUrl === 'stun:stun.cloudflare.com:3478'
      ? 'Проверка использует публичный STUN Cloudflare; TURN не подключён.' : controlledStunUrl
      ? 'Проверка использует один локальный STUN-узел; TURN не подключён.'
      : 'Браузер использует только host ICE; APK использует профиль установленной сборки. Путь через NAT может быть недоступен.'}</p>
    <button type="button" disabled={!token || !!active} onClick={begin} className="mt-2 rounded-md border border-border px-3 py-1.5 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-ring">Проверить прямой канал</button>
    {active && <button type="button" onClick={() => { stop.current?.(); stop.current = null; }} className="ml-2 rounded-md border border-border px-3 py-1.5">Остановить</button>}
    {result && <div className="mt-3 space-y-2">
      <div role="status" className="font-medium">{phaseText[result.state]}</div>
      <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        <div><dt className="text-muted-foreground">ICE-профиль браузера</dt><dd>{result.iceProfile === 'turn'
          ? 'Временный TURN-доступ' : result.iceProfile === 'public-stun'
          ? 'Публичный STUN · Cloudflare' : result.iceProfile === 'controlled-stun' ? 'Локальный STUN'
          : result.iceProfile === 'host' ? 'Host ICE' : 'Не измерен'}</dd></div>
        <div><dt className="text-muted-foreground">Ответы APK</dt><dd>{result.samples.length} / 20</dd></div>
        <div><dt className="text-muted-foreground">RTT p95</dt><dd>{p95 ? `${p95} мс` : 'Не измерен'}</dd></div>
        <div><dt className="text-muted-foreground">Выбранный ICE-путь</dt><dd>{({ host: 'Host-кандидаты', nat: 'Через NAT', relay: 'Ретранслятор', unknown: 'Не подтверждён' })[result.path]}{result.protocol && ` · ${result.protocol.toUpperCase()}`}</dd></div>
      </dl>
      {result.reason && <p className="break-words text-sm text-muted-foreground">{reasonText[result.reason] ?? 'Проверка завершилась с ошибкой. Автоматического повтора нет.'}</p>}
      {result.reason && <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">Техническая причина</summary><code>{result.reason}</code></details>}
      {result.network && <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">Сетевые этапы проверки</summary>
        <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div><dt>ICE / DTLS</dt><dd>{result.iceState ?? 'Не измерен'} / {result.network.dtlsState ?? 'Не измерен'}</dd></div>
          <div><dt>Адреса браузера / APK</dt><dd>{result.network.localCandidates} / {result.network.remoteCandidates}</dd></div>
          <div><dt>Пары: проверка / отказ / успех</dt><dd>{result.network.checkingPairs} / {result.network.failedPairs} / {result.network.succeededPairs} из {result.network.pairs}</dd></div>
          <div><dt>ICE-запросы / ответы</dt><dd>{result.network.requestsSent ?? 'Не измерены'} / {result.network.responsesReceived ?? 'Не измерены'}</dd></div>
          {result.networkAgeAtStopMs !== undefined && <div><dt>Возраст среза при остановке</dt><dd>{Math.round(result.networkAgeAtStopMs)} мс</dd></div>}
        </dl>
        <p className="mt-2">Сводка последнего браузерного среза. Успешная пара не означает выбранный путь или подтверждённое действие Android. IP и сетевые ключи здесь не сохраняются.</p>
      </details>}
    </div>}
  </section>;
}
