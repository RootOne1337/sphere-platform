'use client';

import { Button } from '@/components/ui/button';

export function CatalogPagination({ page, perPage, total, busy, label, onPageChange }: {
  page: number; perPage: number; total: number; busy: boolean; label: string;
  onPageChange: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / perPage));
  return (
    <nav aria-label={`Страницы: ${label}`} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-3">
      <p className="text-sm text-muted-foreground" aria-live="polite">Страница {page} из {pages} · всего {total}</p>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" disabled={busy || page <= 1} onClick={() => onPageChange(page - 1)} aria-label={`Предыдущая страница: ${label}`}>Назад</Button>
        <Button variant="outline" size="sm" disabled={busy || page >= pages} onClick={() => onPageChange(page + 1)} aria-label={`Следующая страница: ${label}`}>Далее</Button>
      </div>
    </nav>
  );
}
