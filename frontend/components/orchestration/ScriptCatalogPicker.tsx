'use client';

import { useEffect, useState } from 'react';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { scriptCatalogReadFailure, useScriptCatalog, type ScriptCatalogItem } from '@/lib/hooks/useScriptCatalog';
import { formatScriptStepCount } from '@/src/features/scripts/scriptPresentation';
import { Button } from '@/src/shared/ui/button';
import { CatalogPagination } from '@/src/shared/ui/catalog-pagination';
import { Input } from '@/src/shared/ui/input';

const PAGE_SIZE = 50;

export function ScriptCatalogPicker({ value, onChange, label }: {
  value: string;
  onChange: (id: string, item?: ScriptCatalogItem) => void;
  label: string;
}) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<ScriptCatalogItem>();
  const query = useDebounce(search.trim(), 300);
  const searching = query !== search.trim();
  const catalog = useScriptCatalog({ page, per_page: PAGE_SIZE, state: 'active', query: query || undefined });
  const data = catalog.isSuccess && !searching ? catalog.data : undefined;
  const correcting = !!data && page > Math.max(1, data.pages);
  const items = correcting ? [] : data?.items ?? [];

  useEffect(() => {
    if (correcting && data) setPage(Math.max(1, data.pages));
  }, [correcting, data]);

  return <div className="space-y-2 rounded-xl border border-border p-3">
    <Input aria-label={`Поиск: ${label}`} placeholder="Название сценария…" value={search} onChange={event => {
      setSearch(event.target.value);
      setPage(1);
    }} />
    <select aria-label={label} value={value} disabled={!data || correcting} onChange={event => {
      const id = event.target.value;
      const item = items.find(candidate => candidate.id === id);
      setSelected(item);
      onChange(id, item);
    }} className="h-9 w-full rounded-md border border-border bg-card px-2 text-sm text-foreground">
      <option value="">Выберите сценарий…</option>
      {!!value && !items.some(item => item.id === value) && <option value={value}>{selected?.id === value ? selected.name : value} · выбран ранее</option>}
      {items.map(item => <option key={item.id} value={item.id} disabled={!item.current_version_id}>
        {item.name} ({formatScriptStepCount(item.node_count)}){item.current_version_id ? '' : ' · нет публикации'}
      </option>)}
    </select>
    {(searching || correcting || catalog.isPending) && <p role="status" className="text-xs text-muted-foreground">Загрузка каталога сценариев…</p>}
    {catalog.isError && !searching && <div role="alert" className="space-y-1 text-sm text-destructive">
      <p>{scriptCatalogReadFailure(catalog.error)}</p>
      <Button variant="outline" size="sm" disabled={catalog.isFetching} onClick={() => { void catalog.refetch(); }}>Повторить чтение каталога</Button>
    </div>}
    {data && !correcting && (data.total > 0
      ? <CatalogPagination page={page} perPage={PAGE_SIZE} total={data.total} busy={catalog.isFetching} label={label} onPageChange={setPage} />
      : <p className="text-xs text-muted-foreground">{query ? 'По запросу сценариев нет.' : 'В каталоге нет активных сценариев.'}</p>)}
  </div>;
}
