import { ArrowDown, Network, Video } from 'lucide-react';
type Props = { compact?: boolean; direct: boolean; directInput: boolean; live: boolean; rtt: number | null;
  width: number | null; height: number | null; fps: number | null; bitrate: number | null };
const number = (n: number | null, maximum: number) => n !== null && Number.isFinite(n) && n >= 0 && n <= maximum ? n : null;
export function StreamStatusLine(props: Props) {
  const rtt = number(props.rtt, 86_400_000);
  const fps = props.live ? number(props.fps, 240) : null;
  const bitrate = props.live ? number(props.bitrate, 1_000_000_000) : null;
  const size = props.width && props.height ? `${props.width} × ${props.height}` : '—';
  if (props.compact) return <div aria-label="Сводка видеопотока" className="stream-compact-status flex min-w-0 items-center justify-between gap-2 tabular-nums" title={`${props.direct ? 'Прямой канал' : 'Серверный канал'} · ${size} · ${fps === null ? 'FPS не измерен' : `${fps.toFixed(0)} FPS`} · ${bitrate === null ? 'битрейт не измерен' : `${(bitrate / 1_000_000).toFixed(1)} Мбит/с`}`}>
    <span className="inline-flex min-w-0 items-center gap-1.5 truncate"><span className={`h-1.5 w-1.5 shrink-0 rounded-full ${props.live ? 'bg-emerald-400' : 'bg-zinc-400'}`} aria-hidden />{props.direct ? 'Напрямую' : 'Сервер'}</span>
    <span className="shrink-0" title={props.direct ? 'Сетевой RTT, не задержка изображения' : 'RTT браузер ↔ сервер, не до APK'}>{(!props.direct || props.live) && rtt !== null ? `${rtt.toFixed(rtt < 10 ? 1 : 0)} мс` : '—'}</span>
  </div>;
  // Live RTT/ACK/bitrate text must never reflow the canvas during a held gesture.
  // Keep one line; narrow screens can scroll the summary without widening the page.
  return <div aria-label="Сводка видеопотока" className="flex shrink-0 items-center gap-x-3 overflow-x-auto whitespace-nowrap border-b border-border bg-muted/30 px-3 py-1.5 text-[11px] tabular-nums text-muted-foreground [scrollbar-width:none] [&::-webkit-scrollbar]:hidden [&>span]:shrink-0">
    <span className="inline-flex items-center gap-1.5 font-medium text-foreground" title={props.directInput ? 'Видео и непрерывные касания идут напрямую с APK.' : props.direct ? 'Видео идёт напрямую с APK; маршрут управления отображается отдельно.' : 'Видео передаётся через сервер.'}>
      <span className={`h-1.5 w-1.5 rounded-full ${props.live ? 'bg-emerald-500' : 'bg-muted-foreground'}`} aria-hidden />
      {props.direct ? props.directInput ? 'Прямой канал · видео и касания' : 'Видео напрямую' : 'Через сервер'}
    </span>
    <span className="inline-flex items-center gap-1" title={props.direct
      ? 'RTT выбранного сетевого пути. Это не полная задержка от экрана Android до браузера.'
      : 'Круговое время WebSocket браузер ↔ сервер, включая очередь сервера и обработку браузером. Это не RTT до APK, не ACK действия Android и не полная задержка видео.'}><Network className="h-3 w-3" aria-hidden />{props.direct ? 'RTT' : 'RTT сервера'} {(!props.direct || props.live) && rtt !== null ? `${rtt.toFixed(rtt < 10 ? 1 : 0)} мс` : '—'}</span>
    <span className="inline-flex items-center gap-1"><Video className="h-3 w-3" aria-hidden />{size}</span>
    <span title="Фактическая частота декодирования в браузере">{fps === null ? '—' : fps.toFixed(0)} FPS</span>
    <span className="inline-flex items-center gap-1" title="Измеренный получаемый видеобитрейт. Это не максимальная скорость вашей сети."><ArrowDown className="h-3 w-3" aria-hidden />{bitrate === null ? '—' : (bitrate / 1_000_000).toFixed(1)} Мбит/с</span>
  </div>;
}
