'use client';

import { useRef, useState } from 'react';
import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, RefreshCw } from 'lucide-react';
import { api } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { CatalogPagination } from '@/src/shared/ui/catalog-pagination';
import {
  DELIVERY_PAGE_SIZE, DELIVERY_STATUSES, deliveryReason, isDeliveryId, parseDelivery, parseDeliveryDetail,
  parseDeliveryPage, type DeliveryStatus, type WebhookDelivery,
} from './deliveryContract';

const deliveryLabels: Record<DeliveryStatus, string> = {
  pending: 'В очереди',
  sending: 'Отправляется',
  delivered: 'Доставлено',
  dead: 'Закрыто с ошибкой',
};
const attemptLabels = {
  sending: 'Отправляется',
  delivered: 'Доставлено',
  retry: 'Назначен повтор',
  dead: 'Закрыто с ошибкой',
  unknown: 'Исход неизвестен',
};
const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'UTC', dateStyle: 'short', timeStyle: 'medium',
});
const deliveriesPath = '/n8n/deliveries';
const deliveryKey = (scope: string, id: string) => ['webhook-delivery', scope, id];
const replayKey = (scope: string, id: string | null) => ['webhook-replay', scope, id];

function DateValue({ value }: { value: string | null }) {
  return value ? <time dateTime={value}>{dateFormatter.format(new Date(value))} UTC</time> : <>—</>;
}

function DeliveryBadge({ row }: { row: WebhookDelivery }) {
  const label = row.status === 'pending' && row.attempts_count > 0 && row.last_error !== null
    ? 'Ожидает повтора'
    : deliveryLabels[row.status];
  return <Badge variant={row.status === 'delivered' ? 'success' : row.status === 'dead' ? 'destructive' : 'secondary'}>{label}</Badge>;
}

function DeliveryResponse({ status, error }: { status: number | null; error: string | null }) {
  if (status === null) return <>{deliveryReason(error)}</>;
  return <>HTTP {status}{error && <> · {deliveryReason(error)}</>}</>;
}

export function DeliveryHistory({ scope, canReplay, webhookId }: { scope: string; canReplay: boolean; webhookId?: string }) {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<DeliveryStatus | ''>('');
  const [openedId, setOpenedId] = useState<string | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const refreshButton = useRef<HTMLButtonElement | null>(null);
  const replayInFlight = useIsMutating({ mutationKey: replayKey(scope, openedId), exact: true }) > 0;
  const list = useQuery({
    queryKey: ['webhook-deliveries', scope, page, status, webhookId],
    queryFn: async ({ signal }) => {
      const { data } = await api.get(deliveriesPath, { params: {
        page, per_page: DELIVERY_PAGE_SIZE, ...(status ? { status } : {}), ...(webhookId ? { webhook_id: webhookId } : {}),
      }, signal });
      return parseDeliveryPage(data, page, status, webhookId);
    },
    retry: false,
    refetchInterval: 15_000,
  });
  return <section aria-label="Журнал доставки" className="space-y-4">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <label className="space-y-1 text-sm">
        <span className="block font-medium">Статус доставки</span>
        <select className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
          value={status} onChange={event => {
            const next = event.target.value as DeliveryStatus;
            setStatus(DELIVERY_STATUSES.includes(next) ? next : '');
            setPage(1);
          }}>
          <option value="">Все статусы</option>
          {DELIVERY_STATUSES.map(value => <option key={value} value={value}>{deliveryLabels[value]}</option>)}
        </select>
      </label>
      <Button ref={refreshButton} variant="outline" size="sm" disabled={list.isFetching} onClick={() => void list.refetch()}>
        <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />Обновить журнал
      </Button>
    </div>
    {list.isPending ? <p role="status" className="text-sm text-muted-foreground">Загружаем доставки…</p>
      : list.isError ? <p role="alert" className="text-sm text-destructive">Журнал доставки недоступен. Обновите журнал.</p>
        : <>
          {!list.data.items.length ? <p className="rounded-xl border bg-card p-6 text-sm text-muted-foreground">
            {list.data.total ? 'На этой странице нет доставок. Вернитесь к предыдущей странице.' : 'По этим условиям доставок пока нет.'}
          </p> : <div className="overflow-x-auto rounded-xl border bg-card">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="border-b bg-muted/40 text-xs text-muted-foreground"><tr>
                {['Событие и получатель', 'Состояние', 'Попытки', 'Следующая попытка', 'Доставка'].map(label =>
                  <th key={label} scope="col" className="px-4 py-3 font-medium">{label}</th>)}
              </tr></thead>
              <tbody className="divide-y divide-border">
                {list.data.items.map(row => <tr key={row.id}>
                  <td className="px-4 py-3">
                    <p className="break-all font-mono text-xs">{row.event_type}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{row.source === 'subscription' ? 'Подписка' : 'Callback задачи'}</p>
                  </td>
                  <td className="px-4 py-3"><DeliveryBadge row={row} /></td>
                  <td className="px-4 py-3 tabular-nums">{row.attempts_count} / {row.max_attempts}</td>
                  <td className="px-4 py-3 text-xs"><DateValue value={row.status === 'pending' ? row.next_attempt_at : null} /></td>
                  <td className="px-4 py-3">
                    <Button size="sm" variant="ghost" aria-label={`Открыть доставку ${row.id}`}
                      onClick={event => { trigger.current = event.currentTarget; setOpenedId(row.id); }}>
                      <span className="font-mono">{row.id.slice(0, 8)}</span>
                    </Button>
                  </td>
                </tr>)}
              </tbody>
            </table>
          </div>}
          {(list.data.total > DELIVERY_PAGE_SIZE || page > 1) && <CatalogPagination page={page} perPage={DELIVERY_PAGE_SIZE}
            total={list.data.total} busy={list.isFetching} label="доставки" onPageChange={setPage} />}
        </>}
    <Dialog open={openedId !== null} onOpenChange={open => { if (!open && !replayInFlight) setOpenedId(null); }}>
      <DialogContent layout="workspace" className="max-w-3xl" onCloseAutoFocus={event => {
        event.preventDefault();
        (trigger.current?.isConnected ? trigger.current : refreshButton.current)?.focus();
      }}>
        <DialogHeader>
          <DialogTitle>Сведения о доставке</DialogTitle>
          <DialogDescription>История отправки и ответы получателя.</DialogDescription>
        </DialogHeader>
        {openedId && isDeliveryId(openedId) &&
          <DeliveryDetails key={openedId} id={openedId} scope={scope} canReplay={canReplay} />}
      </DialogContent>
    </Dialog>
  </section>;
}

function DeliveryDetails({ id, scope, canReplay }: { id: string; scope: string; canReplay: boolean }) {
  const qc = useQueryClient();
  const lock = useRef(false);
  const [confirm, setConfirm] = useState(false);
  const [outcome, setOutcome] = useState<'idle' | 'accepted' | 'unknown'>('idle');
  const pendingReplayCount = useRef<number | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle');
  const path = `${deliveriesPath}/${id}`;
  const key = deliveryKey(scope, id);
  const detail = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => parseDeliveryDetail((await api.get(path, { signal })).data, id),
    retry: false,
    // Opening the dialog must confirm current eligibility before replay.
    refetchOnMount: 'always',
  });
  const replay = useMutation({
    mutationKey: replayKey(scope, id),
    mutationFn: async (oldReplayCount: number) => {
      const { data } = await api.post(`${path}/replay`);
      const receipt = parseDelivery(data, id);
      if (receipt.status !== 'pending' || receipt.replay_count !== oldReplayCount + 1) {
        throw new Error('Invalid webhook replay receipt');
      }
    },
    retry: false,
    onSuccess: async () => {
      setOutcome('accepted');
      await Promise.all([
        qc.invalidateQueries({ queryKey: key }),
        qc.invalidateQueries({ queryKey: ['webhook-deliveries', scope] }),
      ]);
    },
    onError: () => {
      setOutcome('unknown');
      void qc.invalidateQueries({ queryKey: ['webhook-deliveries', scope] });
    },
    onSettled: () => { lock.current = false; },
  });

  async function reread() {
    setConfirm(false);
    const result = await detail.refetch();
    if (result.isSuccess && outcome === 'unknown') {
      setOutcome(pendingReplayCount.current !== null && result.data.replay_count > pendingReplayCount.current ? 'accepted' : 'idle');
    }
  }

  async function copyId() {
    try { await navigator.clipboard.writeText(id); setCopyState('copied'); }
    catch { setCopyState('error'); }
  }

  const row = detail.data;
  const eligible = canReplay && row?.can_replay && outcome === 'idle' && !detail.isFetching && !detail.isError && !replay.isPending;
  return <>
    <DialogBody className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <code className="select-all break-all text-xs">{id}</code>
        <Button type="button" variant="outline" size="sm" onClick={() => void copyId()}>
          <Copy className="mr-1 h-3.5 w-3.5" aria-hidden="true" />{copyState === 'copied' ? 'ID скопирован' : 'Скопировать ID'}
        </Button>
      </div>
      {copyState === 'error' && <p role="status" className="text-xs text-muted-foreground">Выделите ID и скопируйте вручную.</p>}
      {outcome === 'accepted' && <p role="status" className="text-sm text-muted-foreground">Повтор поставлен в очередь с тем же ID доставки.</p>}
      {outcome === 'unknown' && <p role="alert" className="text-sm text-destructive">Исход запроса повтора неизвестен. Сначала обновите сведения о доставке.</p>}
      {detail.isPending ? <p role="status">Загружаем сведения…</p>
        : detail.isError ? <p role="alert" className="text-sm text-destructive">Сведения о доставке недоступны.</p>
          : row && <>
            <dl className="grid gap-x-6 gap-y-3 rounded-xl border p-3 text-sm sm:grid-cols-2">
              <div><dt className="text-xs text-muted-foreground">Состояние</dt><dd className="mt-1"><DeliveryBadge row={row} /></dd></div>
              <div><dt className="text-xs text-muted-foreground">Событие</dt><dd className="break-all font-mono text-xs">{row.event_type}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Создано</dt><dd><DateValue value={row.created_at} /></dd></div>
              <div><dt className="text-xs text-muted-foreground">Обновлено</dt><dd><DateValue value={row.updated_at} /></dd></div>
              <div><dt className="text-xs text-muted-foreground">{row.status === 'sending' ? 'Срок ожидания обработчика' : 'Следующая попытка'}</dt><dd><DateValue value={row.next_attempt_at} /></dd></div>
              <div><dt className="text-xs text-muted-foreground">Последний ответ</dt>
                <dd><DeliveryResponse status={row.last_http_status} error={row.last_error} /></dd></div>
              <div><dt className="text-xs text-muted-foreground">Попытки</dt><dd>{row.attempts_count} / {row.max_attempts}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Ручные повторы</dt><dd>{row.replay_count}</dd></div>
              {row.subject_id && <div><dt className="text-xs text-muted-foreground">ID связанной записи</dt><dd className="break-all font-mono text-xs">{row.subject_id}</dd></div>}
              {row.webhook_id && <div><dt className="text-xs text-muted-foreground">ID подписки</dt><dd className="break-all font-mono text-xs">{row.webhook_id}</dd></div>}
            </dl>
            <h3 className="text-sm font-medium">Попытки доставки</h3>
            {row.attempts.length ? <ol className="divide-y rounded-xl border">
              {row.attempts.map(attempt => <li key={attempt.number} className="grid gap-1 p-3 text-sm sm:grid-cols-[auto_1fr_1fr]">
                <span className="font-medium">№ {attempt.number} · {attemptLabels[attempt.status]}</span>
                <span><DeliveryResponse status={attempt.http_status} error={attempt.error} /></span>
                <span className="text-xs text-muted-foreground">
                  Начало <DateValue value={attempt.started_at} />
                  <br />Конец <DateValue value={attempt.finished_at} />
                </span>
              </li>)}
            </ol> : <p className="text-sm text-muted-foreground">Попыток пока нет.</p>}
          </>}
      {confirm && eligible && <p className="rounded-lg border p-3 text-sm">
        Получатель может обработать событие повторно. Повтор использует исходный ID доставки.
      </p>}
    </DialogBody>
    <DialogFooter>
      <Button variant="outline" size="sm" disabled={detail.isFetching || replay.isPending} onClick={() => void reread()}>Обновить сведения</Button>
      {eligible && !confirm && <Button size="sm" onClick={() => setConfirm(true)}>Повторить доставку</Button>}
      {eligible && confirm && row && <>
        <Button variant="outline" size="sm" onClick={() => setConfirm(false)}>Отмена</Button>
        <Button size="sm" onClick={() => {
          if (lock.current) return;
          lock.current = true;
          pendingReplayCount.current = row.replay_count;
          setConfirm(false);
          replay.mutate(row.replay_count);
        }}>Подтвердить повтор</Button>
      </>}
      {replay.isPending && <p role="status" className="text-sm text-muted-foreground">Запрашиваем повтор…</p>}
    </DialogFooter>
  </>;
}
