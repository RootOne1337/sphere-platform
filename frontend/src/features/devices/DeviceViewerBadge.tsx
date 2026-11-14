import { Eye, MonitorPlay } from 'lucide-react';
export function DeviceViewerBadge({ card, stream, showEmpty = false }: { card?: number | null; stream?: number | null; showEmpty?: boolean }) {
  const valid = (value?: number | null) => typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 128 ? value : null;
  const cards = valid(card), streams = valid(stream);
  if (!showEmpty && !cards && !streams) return null;
  if (cards === null && streams === null) return showEmpty ? <span className="text-xs text-muted-foreground">Зрители: —</span> : null;
  return <span aria-label={`Открытые карточки: ${cards ?? 'неизвестно'}. Видеопоток: ${streams ?? 'неизвестно'}.`}
    title="Активные вкладки: один пользователь с несколькими вкладками учитывается отдельно. Закрытый сеанс исчезает не позднее 45 секунд."
    className="inline-flex shrink-0 items-center gap-2 rounded-md border border-border/70 bg-muted/40 px-1.5 py-0.5 text-[10px] tabular-nums text-muted-foreground">
    {(showEmpty || !!cards) && <span className="inline-flex items-center gap-1"><Eye className="h-3 w-3" aria-hidden />{cards ?? '—'}</span>}
    {(showEmpty || !!streams) && <span className="inline-flex items-center gap-1 text-primary"><MonitorPlay className="h-3 w-3" aria-hidden />{streams ?? '—'}</span>}
  </span>;
}
