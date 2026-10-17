'use client';
import { useState } from 'react';
import { Filter } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { AuditQueryBuilder } from './AuditQueryBuilder';
import { auditFilterParams, EMPTY_AUDIT_DRAFT, type AuditFilters } from './investigation';

export function AuditFiltersForm({ onApply }: { onApply: (params: AuditFilters) => void }) {
  const [draft, setDraft] = useState(EMPTY_AUDIT_DRAFT);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const inputClass = 'h-10 w-full rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
  return <form onSubmit={event => {
    event.preventDefault();
    try { const params = auditFilterParams(draft); setError(''); onApply(params); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Проверьте фильтры.'); }
  }}>
    <div className="flex flex-col gap-3 border-b border-border p-4 sm:p-5 xl:flex-row xl:items-center">
      <div className="min-w-0 flex-1"><AuditQueryBuilder value={draft.q} onChange={q => setDraft(current => ({ ...current, q }))} /></div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant={open ? 'secondary' : 'outline'} onClick={() => setOpen(value => !value)} aria-expanded={open}><Filter className="mr-2 h-4 w-4" />Фильтры</Button>
        <Button type="submit">Применить фильтры</Button>
        <Button type="button" variant="ghost" onClick={() => { setDraft(EMPTY_AUDIT_DRAFT); setError(''); onApply({}); }}>Сбросить</Button>
      </div>
    </div>
    {open && <div className="grid gap-3 border-b border-border bg-muted/30 p-4 sm:grid-cols-2 sm:p-5 xl:grid-cols-3" aria-label="Фильтры журнала">
      <label className="grid gap-1.5 text-sm font-medium">Результат
        <select className={inputClass} value={draft.status} onChange={event => setDraft(current => ({ ...current, status: event.target.value }))}>
          <option value="">Все результаты</option><option value="SUCCESS">Успешно</option><option value="FAILED">Ошибка</option><option value="WARNING">Предупреждение</option><option value="UNKNOWN">Не указано</option>
        </select>
      </label>
      <label className="grid gap-1.5 text-sm font-medium">Действие содержит<input className={inputClass} maxLength={255} value={draft.action} onChange={event => setDraft(current => ({ ...current, action: event.target.value }))} placeholder="put.groups" /></label>
      <label className="grid gap-1.5 text-sm font-medium">UUID пользователя<input className={inputClass} value={draft.user_id} onChange={event => setDraft(current => ({ ...current, user_id: event.target.value }))} placeholder="Полный UUID" /></label>
      <label className="grid gap-1.5 text-sm font-medium">Тип ресурса<input className={inputClass} maxLength={100} value={draft.resource_type} onChange={event => setDraft(current => ({ ...current, resource_type: event.target.value }))} placeholder="groups" /></label>
      <label className="grid gap-1.5 text-sm font-medium">С (UTC)<input className={inputClass} type="datetime-local" step="1" value={draft.from} onChange={event => setDraft(current => ({ ...current, from: event.target.value }))} /></label>
      <label className="grid gap-1.5 text-sm font-medium">По (UTC)<input className={inputClass} type="datetime-local" step="1" value={draft.to} onChange={event => setDraft(current => ({ ...current, to: event.target.value }))} /></label>
    </div>}
    <div className="border-b border-border px-4 py-3 text-xs leading-5 text-muted-foreground sm:px-5">
      Поиск и фильтры применяются ко всему журналу организации после нажатия «Применить». Условия объединяются через И. Диапазон включает обе границы; время вводится в UTC. CSV использует применённые условия, до 5 000 событий за один запрос.
    </div>
    {error && <p role="alert" className="border-b border-border px-5 py-3 text-sm text-destructive">{error}</p>}
  </form>;
}
