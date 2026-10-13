import { ArrowDown, Network, Video } from 'lucide-react';
type Props = { direct: boolean; directInput: boolean; live: boolean; rtt: number | null;
  width: number | null; height: number | null; fps: number | null; bitrate: number | null };
const number = (n: number | null, maximum: number) => n !== null && Number.isFinite(n) && n >= 0 && n <= maximum ? n : null;
export function StreamStatusLine(props: Props) {
  const rtt = number(props.rtt, 86_400_000);
  const fps = props.live ? number(props.fps, 240) : null;
  const bitrate = props.live ? number(props.bitrate, 1_000_000_000) : null;
  const size = props.width && props.height ? `${props.width} × ${props.height}` : '—';
  return <div aria-label="Сводка видеопотока" className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-muted/30 px-3 py-1.5 text-[11px] tabular-nums text-muted-foreground">
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
