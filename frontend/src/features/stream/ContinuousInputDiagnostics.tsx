import type { PointerFenceObservation } from './continuousPointer';

const actionNames: Record<number, string> = { 0: 'DOWN', 1: 'UP', 2: 'MOVE', 3: 'CANCEL', 4: 'HEARTBEAT' };
const milliseconds = (value: number | null) => value === null ? 'нет измерения' : `${Math.round(value)} мс`;

/** The last failure in this viewer only. No polling, persistence, or global fleet claims. */
export function ContinuousInputDiagnostics({ snapshot }: { snapshot: PointerFenceObservation }) {
  return <details className="my-2 rounded border border-amber-300/30 p-2" open>
    <summary className="cursor-pointer font-semibold text-amber-200">Последний сбой управления · {snapshot.reason}</summary>
    <dl className="mt-2 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-3 gap-y-1 break-words">
      <dt>Фаза при остановке</dt><dd>{snapshot.phase}</dd>
      <dt>Отправлено / подтверждено</dt><dd>№{snapshot.offeredSequence} / №{snapshot.acknowledgedSequence}</dd>
      <dt>Ожидали ACK</dt><dd>{snapshot.pendingCount}</dd>
      <dt>Самая старая команда</dt><dd>{snapshot.oldestSequence === null ? 'нет' : `№${snapshot.oldestSequence} · ${actionNames[snapshot.oldestAction!] ?? 'UNKNOWN'}`}</dd>
      <dt>Возраст / отсчёт deadline</dt><dd>{milliseconds(snapshot.oldestAgeMs)} / {milliseconds(snapshot.oldestDeadlineAgeMs)}</dd>
      <dt>Разрыв тиков браузера</dt><dd>{milliseconds(snapshot.tickGapMs)}</dd>
      <dt>Последний ACK: RTT / возраст</dt><dd>{milliseconds(snapshot.lastReceiptRoundTripMs)} / {milliseconds(snapshot.lastReceiptAgeMs)}</dd>
      <dt>С последней отправки</dt><dd>{milliseconds(snapshot.lastSendAgeMs)}</dd>
      <dt>Касание / terminal ACK</dt><dd>{snapshot.pointerHeld ? 'палец удерживался' : 'палец не удерживался'} · {snapshot.terminalSequence === null ? 'не ожидался' : `№${snapshot.terminalSequence} · ${milliseconds(snapshot.terminalAgeMs)}`}</dd>
      <dt>WebSocket / буфер</dt><dd>{snapshot.socketState === 1 ? 'OPEN' : snapshot.socketState} · {snapshot.bufferedBytes === null ? 'нет измерения' : `${snapshot.bufferedBytes} B`}</dd>
    </dl>
    <p className="mt-2 text-white/70">{snapshot.idleHeartbeatOnly ? 'Задержался только heartbeat без касания. ' : ''}Это состояние браузера в момент остановки. RTT включает весь путь до подтверждения Android; участок задержки ещё не определён. Команды не повторяются.</p>
  </details>;
}
