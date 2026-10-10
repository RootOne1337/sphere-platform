'use client';

import { useEffect, useState } from 'react';
import { Input } from '@/src/shared/ui/input';
import { Button } from '@/src/shared/ui/button';
import { CatalogPagination } from '@/src/shared/ui/catalog-pagination';
import { CATALOG_PER_PAGE, useCatalogPage } from '@/src/features/orchestration/useCatalogPage';

interface PipelineOption { id: string; name: string; version: number; is_active: boolean }

/** Browsing catalog pages never implicitly changes the schedule's saved target. */
export function PipelineCatalogPicker({ value, onChange, enabled }: { value: string; onChange: (id: string) => void; enabled: boolean }) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<PipelineOption | null>(null);
  const query = useCatalogPage<PipelineOption>('pipelines', page, {}, { enabled, polling: false });
  const items = query.isSuccess ? query.data.items : [];
  const visible = items.filter(item => item.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()) || item.id.includes(search.trim()));
  const selectedItem = items.find(item => item.id === value) ?? (selected?.id === value ? selected : null);
  const selectionOutsideResults = !!value && !visible.some(item => item.id === value);
  const correctingPage = query.isSuccess && page > Math.max(1, query.data.pages);
  useEffect(() => {
    if (query.isSuccess && correctingPage) setPage(Math.max(1, query.data.pages));
  }, [query.isSuccess, query.data, correctingPage]);
  useEffect(() => {
    if (selectedItem && selectedItem !== selected) setSelected(selectedItem);
  }, [selectedItem, selected]);

  return <div className="space-y-2 rounded-xl border border-border p-3">
    <Input aria-label="Поиск конвейера на странице выбора" placeholder="Имя или ID на этой странице…" value={search} onChange={event => setSearch(event.target.value)} />
    <p className="text-xs text-muted-foreground">Поиск в загруженной странице. Переход между страницами сохраняет выбранную цель.</p>
    <select aria-label="Конвейер расписания" value={value} disabled={query.isPending || query.isError || correctingPage} onChange={event => {
      const next = event.target.value;
      setSelected(items.find(item => item.id === next) ?? null);
      onChange(next);
    }} className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm text-foreground">
      <option value="">Выбери pipeline...</option>
      {selectionOutsideResults && <option value={value}>{selectedItem ? `${selectedItem.name} (v${selectedItem.version})` : value} — сохранённая цель</option>}
      {visible.map(item => <option key={item.id} value={item.id}>{item.name} (v{item.version}){item.is_active ? '' : ' · неактивен'}</option>)}
    </select>
    {!!value && <p className="break-all text-xs text-muted-foreground">Выбранный ID: <code>{value}</code></p>}
    {query.isError && <div role="alert" className="text-sm text-destructive">Не удалось загрузить конвейеры для выбора. Сохранённый ID не изменён.
      <Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => { void query.refetch(); }}>Повторить выбор конвейера</Button>
    </div>}
    {(query.isPending || correctingPage) && <p role="status" className="text-xs text-muted-foreground">Загружаем страницу конвейеров…</p>}
    {query.isSuccess && !correctingPage && visible.length === 0 && <p className="text-xs text-muted-foreground">{search.trim() ? 'На этой странице совпадений нет.' : 'Каталог конвейеров пуст.'}</p>}
    {query.isSuccess && !correctingPage && <CatalogPagination page={page} perPage={CATALOG_PER_PAGE} total={query.data.total} busy={query.isFetching} label="конвейеры для расписания" onPageChange={setPage} />}
  </div>;
}
