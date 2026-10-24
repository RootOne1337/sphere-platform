'use client';

import { CalendarClock, Code2, Fingerprint, Globe2, Shield } from 'lucide-react';
import type { AuditEvent } from '@/src/features/audit/types';
import { Badge } from '@/src/shared/ui/badge';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';

interface AuditDrawerProps {
  event: AuditEvent | null;
  onClose: () => void;
}

const VISIBLE_META_FIELDS = ['status', 'http_status', 'duration_ms', 'request_id', 'trace_id'] as const;

function displayValue(value: unknown) {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '—';
}

export function AuditDrawer({ event, onClose }: AuditDrawerProps) {
  if (!event) return null;
  const metadata = VISIBLE_META_FIELDS
    .filter((key) => event.meta[key] !== undefined && event.meta[key] !== null)
    .map((key) => ({ key, value: displayValue(event.meta[key]) }));

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="!fixed !left-auto !right-0 !top-0 !h-dvh !max-h-dvh !w-full !max-w-xl !translate-x-0 !translate-y-0 grid-rows-[auto_1fr] gap-0 rounded-none border-l p-0 sm:rounded-none">
        <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-4 sm:px-6">
          <div className="flex min-w-0 items-start gap-3">
            <span className="rounded-xl bg-primary/10 p-2.5 text-primary"><Shield className="h-5 w-5" aria-hidden="true" /></span>
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">Событие аудита</p>
              <DialogTitle className="mt-1 break-all text-base font-semibold">{event.action}</DialogTitle>
              <DialogDescription className="sr-only">Детали события из журнала аудита, полученные от backend.</DialogDescription>
              <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{event.id}</p>
            </div>
          </div>
        </header>

        <div className="flex-1 space-y-5 overflow-y-auto p-5 sm:p-6">
          <section className="grid gap-3 sm:grid-cols-2" aria-label="Данные события">
            <div className="rounded-xl border border-border bg-muted/30 p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><CalendarClock className="h-4 w-4" />Время сервера</div>
              <p className="mt-2 break-words text-sm font-medium">{new Date(event.timestamp).toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'medium' })}</p>
            </div>
            <div className="rounded-xl border border-border bg-muted/30 p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><Fingerprint className="h-4 w-4" />Результат</div>
              <Badge variant={event.status === 'FAILED' ? 'destructive' : event.status === 'WARNING' ? 'warning' : event.status === 'UNKNOWN' ? 'secondary' : 'success'} className="mt-2">{event.status === 'UNKNOWN' ? 'Не указано' : event.status === 'FAILED' ? 'Ошибка' : event.status === 'WARNING' ? 'Предупреждение' : 'Успешно'}</Badge>
            </div>
            <div className="rounded-xl border border-border bg-muted/30 p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><Fingerprint className="h-4 w-4" />Пользователь</div>
              <p className="mt-2 break-all font-mono text-sm">{event.user || 'system'}</p>
            </div>
            <div className="rounded-xl border border-border bg-muted/30 p-4">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><Globe2 className="h-4 w-4" />IP-адрес</div>
              <p className="mt-2 font-mono text-sm">{event.ip || '—'}</p>
            </div>
            <div className="rounded-xl border border-border bg-muted/30 p-4 sm:col-span-2">
              <div className="text-xs font-medium text-muted-foreground">Ресурс</div>
              <p className="mt-2 break-all text-sm">{event.resource}</p>
            </div>
          </section>

          {metadata.length > 0 && (
            <section className="overflow-hidden rounded-xl border border-border" aria-labelledby="audit-meta-heading">
              <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-4 py-3"><Code2 className="h-4 w-4 text-muted-foreground" /><h3 id="audit-meta-heading" className="text-sm font-semibold">Метаданные backend</h3></div>
              <dl className="divide-y divide-border px-4">
                {metadata.map(({ key, value }) => <div key={key} className="flex items-start justify-between gap-4 py-3 text-sm"><dt className="font-mono text-muted-foreground">{key}</dt><dd className="break-all text-right font-medium">{value}</dd></div>)}
              </dl>
            </section>
          )}

          <p className="rounded-xl border border-border bg-muted/25 p-4 text-sm leading-6 text-muted-foreground">
            Здесь показаны поля, которые фактически вернул endpoint журнала аудита. Повторное выполнение операции из записи аудита недоступно.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
