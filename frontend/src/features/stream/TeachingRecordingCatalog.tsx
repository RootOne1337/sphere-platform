'use client';
import {useId, useState} from 'react';
import {ArrowRight, Check, ChevronLeft, ChevronRight, Clock3, Film, FolderOpen, Monitor, RefreshCw, Search} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {selectTeachingCatalog, teachingCatalogControlLabel, teachingCatalogDate, teachingCatalogDuration, teachingCatalogHudLabel, teachingCatalogPresentation, teachingCatalogReason,
  type TeachingCatalogBadge, type TeachingCatalogEntry, type TeachingCatalogFilter, type TeachingCatalogSort} from './teachingCatalog';

export type TeachingRecordingCatalogProps = {
  entries: readonly TeachingCatalogEntry[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onPrepare?: (id: string) => void;
  onReload?: () => void;
  loading?: boolean;
  refreshing?: boolean;
  disabled?: boolean;
  readOnly?: boolean;
  truncated?: boolean;
  nowMs?: number;
  statusStaleAfterMs?: number;
};
const tones = {
  neutral: 'border-border bg-muted/35 text-muted-foreground',
  success: 'border-emerald-600/25 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300',
  working: 'border-sky-600/25 bg-sky-500/10 text-sky-800 dark:text-sky-300',
  warning: 'border-amber-600/25 bg-amber-500/10 text-amber-900 dark:text-amber-300',
  error: 'border-red-600/25 bg-red-500/10 text-red-800 dark:text-red-300',
};
function StateRow({label, state}: {label: string; state: TeachingCatalogBadge}) {
  return <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 text-xs"><dt className="text-muted-foreground">{label}</dt><dd className={`max-w-full break-words rounded-md border px-2 py-1 text-right ${tones[state.tone]}`}>{state.label}</dd></div>;
}
/** A bounded local catalog. Rendering or opening an entry never issues device input or network requests. */
export function TeachingRecordingCatalog({entries, selectedId, onSelect, onPrepare, onReload, loading = false, refreshing = false, disabled = false, readOnly = false,
  truncated = false, nowMs = Date.now(), statusStaleAfterMs = 30000}: TeachingRecordingCatalogProps) {
  const [query, setQuery] = useState(''), [sort, setSort] = useState<TeachingCatalogSort>('newest');
  const [filter, setFilter] = useState<TeachingCatalogFilter>('all'), [page, setPage] = useState(1);
  const searchId = useId(), sortId = useId();
  const catalog = selectTeachingCatalog(entries, {query, sort, filter, page, nowMs, statusStaleAfterMs});
  const filters: {id: TeachingCatalogFilter; label: string}[] = [{id: 'all', label: 'Все записи'}, {id: 'saved', label: 'Видео сохранено'},
    {id: 'processing', label: 'В обработке'}, {id: 'map', label: 'Карта для проверки'}, {id: 'attention', label: 'Требуют внимания'}];
  return <section aria-label="Библиотека записанных маршрутов" aria-busy={loading || refreshing} className="min-w-0 space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[.16em] text-primary"><FolderOpen size={14} aria-hidden="true"/>Библиотека маршрутов</p>
      <h3 className="mt-1 text-xl font-semibold tracking-tight">Записанные проходы</h3><p className="mt-2 max-w-3xl text-xs leading-5 text-muted-foreground">Записи этого браузера и аккаунта. Сохранённое видео, восстановление камер и допуск карты к проверке показаны отдельно.</p></div>
      {onReload && <Button type="button" size="sm" variant="outline" disabled={loading || refreshing || disabled} onClick={onReload}><RefreshCw size={14} aria-hidden="true" className={refreshing ? 'animate-spin motion-reduce:animate-none' : ''}/>{refreshing ? 'Обновляем…' : 'Обновить библиотеку'}</Button>}
    </header>
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4" aria-label="Сводка библиотеки">{[
      ['Видео сохранено', catalog.counts.saved, 'Источник и маркер сохранения'], ['В обработке', catalog.counts.processing, 'Очередь и активный расчёт'],
      ['Карты для проверки', catalog.counts.map, 'Не подтверждает автопроезд'], ['Требуют внимания', catalog.counts.attention, 'Записи или результаты с ошибкой'],
    ].map(([label, value, detail]) => <div key={label} className="min-w-0 rounded-xl border border-border bg-background/65 p-3"><p className="text-[11px] text-muted-foreground">{label}</p><p className="mt-1 text-2xl font-semibold tabular-nums">{loading ? '—' : value}</p><p className="mt-1 text-[10px] leading-4 text-muted-foreground">{detail}</p></div>)}</div>
    {readOnly && <p role="status" className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs leading-5 text-muted-foreground">Режим просмотра: записи и результаты доступны. Подготовка из каталога выключена.</p>}
    {disabled && <p role="status" className="rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-xs leading-5 text-amber-900 dark:text-amber-300">Выбор записи временно недоступен во время текущей операции. Состояние библиотеки сохранено.</p>}
    <div className="space-y-3 rounded-xl border border-border bg-background/40 p-3"><div className="flex flex-col gap-3 sm:flex-row sm:items-end"><label htmlFor={searchId} className="min-w-0 flex-1 space-y-1 text-xs text-muted-foreground"><span>Найти запись</span><span className="relative block"><Search size={15} aria-hidden="true" className="pointer-events-none absolute left-3 top-3"/><input id={searchId} type="search" value={query} onChange={event => {setQuery(event.target.value); setPage(1);}} placeholder="Название, устройство или идентификатор" className="h-10 w-full min-w-0 rounded-lg border border-input bg-background pl-9 pr-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"/></span></label>
      <label htmlFor={sortId} className="space-y-1 text-xs text-muted-foreground"><span className="block">Порядок</span><select id={sortId} value={sort} onChange={event => {setSort(event.target.value as TeachingCatalogSort); setPage(1);}} className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:w-48"><option value="newest">Сначала новые</option><option value="oldest">Сначала старые</option><option value="title">По названию</option></select></label></div>
      <div role="group" aria-label="Фильтр записей" className="flex flex-wrap gap-1.5">{filters.map(item => <Button type="button" key={item.id} size="sm" variant={filter === item.id ? 'secondary' : 'ghost'} aria-pressed={filter === item.id} onClick={() => {setFilter(item.id); setPage(1);}} className="h-auto min-h-8 max-w-full flex-wrap py-1.5"><span>{item.label}</span><span className="rounded bg-background/70 px-1.5 text-[10px] tabular-nums text-muted-foreground">{loading ? '—' : catalog.counts[item.id]}</span></Button>)}</div>
    </div>
    {loading ? <div role="status" className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">Читаем сохранённые записи…</div>
      : entries.length === 0 ? <div className="rounded-xl border border-dashed border-border bg-muted/15 p-6 text-center"><Film size={28} aria-hidden="true" className="mx-auto text-muted-foreground"/><p className="mt-3 font-medium">Записей пока нет</p><p className="mx-auto mt-2 max-w-md text-xs leading-5 text-muted-foreground">Начните запись в режиме «Запись», пройдите маршрут в эмуляторе и сохраните видео. Оно появится здесь; подготовка выполняется отдельно от управления.</p></div>
      : catalog.total === 0 ? <div role="status" className="rounded-xl border border-dashed border-border p-6 text-center"><p className="text-sm font-medium">Записи не найдены</p><p className="mt-1 text-xs text-muted-foreground">Измените поиск или фильтр. Исходные материалы не удалены.</p><Button type="button" size="sm" variant="outline" className="mt-3" onClick={() => {setQuery(''); setFilter('all'); setPage(1);}}>Сбросить поиск и фильтр</Button></div>
      : <ul aria-label="Сохранённые записи" className="grid min-w-0 gap-3 md:grid-cols-2 2xl:grid-cols-3">{catalog.rows.map(({entry}) => {
        const view = teachingCatalogPresentation(entry, {nowMs, statusStaleAfterMs, readOnly});
        const selected = selectedId === entry.id;
        const reason = teachingCatalogReason(entry.sourceFailure || entry.preparation?.reason || entry.navigation?.error);
        const prepare = view.action.kind === 'prepare' && !!onPrepare && !readOnly;
        return <li key={entry.id} className={`flex min-w-0 flex-col overflow-hidden rounded-xl border bg-background/65 ${selected ? 'border-primary/60 ring-1 ring-primary/20' : 'border-border'}`}>
          <div className="flex min-w-0 items-start gap-3 p-4 pb-3"><span aria-hidden="true" className={`rounded-lg border p-2 ${selected ? 'border-primary/25 bg-primary/10 text-primary' : 'border-border bg-muted/35 text-muted-foreground'}`}><Film size={18}/></span><div className="min-w-0 flex-1"><h4 className="break-words text-sm font-semibold leading-5">{entry.title || 'Без названия'}</h4><p className="mt-1 break-words text-[10px] text-muted-foreground">{teachingCatalogDate(entry.createdAt)} · {entry.id.slice(0, 8)}</p></div>{selected && <span className="flex shrink-0 items-center gap-1 text-[10px] font-medium text-primary"><Check size={13} aria-hidden="true"/>Выбрана</span>}</div>
          <div className="space-y-3 px-4 pb-4"><div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground"><span className="inline-flex items-center gap-1.5"><Clock3 size={12} aria-hidden="true"/>{teachingCatalogDuration(entry.durationSeconds)}</span><span>{Number.isFinite(entry.frames) && entry.frames >= 0 ? entry.frames.toLocaleString('ru') : '—'} кадров</span></div>
            <p className="flex min-w-0 items-start gap-1.5 text-xs"><Monitor size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-muted-foreground"/><span className="min-w-0 break-words">{entry.deviceName || entry.deviceId || 'Устройство не указано'}</span></p><div className="flex flex-wrap gap-1.5 text-[10px] text-muted-foreground"><span className="max-w-full break-words rounded-md bg-muted/50 px-2 py-1">{teachingCatalogControlLabel(entry.controlMode)}</span><span className="max-w-full break-words rounded-md bg-muted/50 px-2 py-1">{teachingCatalogHudLabel(entry)}</span></div>
            <dl className="space-y-2 border-t border-border pt-3"><StateRow label="Исходник" state={view.source}/><StateRow label="Реконструкция" state={view.reconstruction}/><StateRow label="Навигация" state={view.navigation}/></dl>
            {view.freshness === 'stale' || view.freshness === 'unknown' ? <p className="min-h-8 text-[10px] leading-4 text-muted-foreground">{view.freshness === 'stale' ? 'Состояние обработки устарело. Откройте запись, чтобы проверить его снова.' : 'Текущее состояние обработки ещё не подтверждено.'}</p> : reason ? <p className="min-h-8 text-[10px] leading-4 text-muted-foreground">{reason}</p> : <p className="min-h-8 text-[10px] leading-4 text-muted-foreground">{view.mapForReview ? 'Карта допущена к проверке; автоматический проезд этим не подтверждён.' : 'Сохранение видео не подтверждает точность геометрии или готовность движения.'}</p>}
          </div>
          <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-border bg-muted/15 px-4 py-3"><Button type="button" size="sm" variant={selected ? 'secondary' : 'outline'} aria-pressed={selected} aria-label={`Открыть запись «${entry.title || 'Без названия'}»`} disabled={disabled} onClick={() => onSelect(entry.id)}>Открыть запись<ArrowRight size={13} aria-hidden="true"/></Button>
            {(prepare || view.action.label !== 'Открыть запись') && <Button type="button" size="sm" variant="ghost" className="max-w-full whitespace-normal text-left" disabled={disabled} onClick={() => prepare ? onPrepare!(entry.id) : onSelect(entry.id)}>{prepare ? view.action.label : view.action.kind === 'prepare' ? 'Проверить результат' : view.action.label}</Button>}
          </div>
        </li>;
      })}</ul>}
    {!loading && entries.length > 0 && <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3"><p role="status" className="text-xs text-muted-foreground">Найдено {catalog.total} из {entries.length} прочитанных записей · страница {catalog.page} из {catalog.pages}</p><nav aria-label="Страницы библиотеки" className="flex items-center gap-2"><Button type="button" size="sm" variant="outline" disabled={catalog.page <= 1} onClick={() => setPage(catalog.page - 1)}><ChevronLeft size={13} aria-hidden="true"/>Назад</Button><Button type="button" size="sm" variant="outline" disabled={catalog.page >= catalog.pages} onClick={() => setPage(catalog.page + 1)}>Далее<ChevronRight size={13} aria-hidden="true"/></Button></nav></footer>}
    {truncated && <p role="status" className="rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-xs leading-5 text-amber-900 dark:text-amber-300">Часть библиотеки не прочитана: достигнут предел безопасного чтения. Поиск и счётчики относятся только к прочитанным записям; другие записи могут не отображаться.</p>}
    <p className="text-[10px] leading-4 text-muted-foreground">«Видео сохранено» относится к исходнику и маркеру сохранения. Качество видео и всей геометрии проверяется отдельно. Выбор и просмотр не запускают управление в игре.</p>
  </section>;
}
