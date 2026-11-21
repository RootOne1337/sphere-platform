'use client';

import { useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, Copy, Plus, Radio, RefreshCw, Trash2, Webhook as WebhookIcon } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { PermissionNotice, useCapabilities } from '@/src/features/access/Capabilities';
import { DeliveryHistory } from '@/src/features/webhooks/DeliveryHistory';

interface WebhookItem {
  id: string;
  name: string;
  url: string;
  events: string[];
  tags: string[];
  is_active: boolean;
  secret: string | null;
  last_triggered_at: string | null;
  failure_count: number;
  created_at: string;
  receiver_allowed?: boolean;
}

interface WebhookListResponse {
  items: WebhookItem[];
  total: number;
  publishing_enabled?: boolean;
  supported_events?: string[];
}
type WebhookChange = { id: string; kind: 'toggle'; isActive: boolean } | { id: string; kind: 'delete' };

function DeliverySummary({ webhook }: { webhook: WebhookItem }) {
  const lastSuccess = webhook.last_triggered_at ? new Date(webhook.last_triggered_at) : null;
  const hasTimestamp = lastSuccess && Number.isFinite(lastSuccess.getTime());
  const failures = Number.isSafeInteger(webhook.failure_count) && webhook.failure_count >= 0
    ? webhook.failure_count
    : null;
  return (
    <dl className="mt-3 grid gap-x-5 gap-y-2 border-t border-border pt-2 text-xs sm:grid-cols-2">
      <div>
        <dt className="font-medium">Последняя зафиксированная доставка</dt>
        <dd className="mt-0.5 text-muted-foreground">
          {hasTimestamp
            ? <time dateTime={lastSuccess.toISOString()}>{lastSuccess.toLocaleString('ru-RU')}</time>
            : 'Успешная доставка не зафиксирована'}
        </dd>
      </div>
      <div>
        <dt className="font-medium">Счётчик отказов</dt>
        <dd className={failures ? 'mt-0.5 font-medium text-destructive' : 'mt-0.5 text-muted-foreground'}>
          {failures ?? 'Нет данных'}
        </dd>
      </div>
    </dl>
  );
}

export default function WebhooksPage() {
  const access = useCapabilities();
  const actor = useAuthStore(state => state.user);
  const sessionVersion = useAuthStore(state => state.sessionVersion);
  const scope = JSON.stringify([actor?.org_id, actor?.id, actor?.role, sessionVersion]);
  if (!access.can('webhook:read')) {
    return <PageFrame>
      <PageHeading title="Вебхуки" />
      <PermissionNotice permission="webhook:read" action="просмотр вебхуков и истории доставки" />
    </PageFrame>;
  }
  return <WebhookWorkspace key={scope} scope={scope} canWrite={access.can('webhook:write')} />;
}

function WebhookWorkspace({ scope, canWrite }: { scope: string; canWrite: boolean }) {
  const qc = useQueryClient();
  const [section, setSection] = useState('subscriptions');
  const [historySubscription, setHistorySubscription] = useState<WebhookItem | null>(null);
  const queryKey = ['webhooks', scope];
  const { data, isLoading, isError, isFetching, refetch } = useQuery<WebhookListResponse>({
    queryKey,
    queryFn: async ({ signal }) => {
      const { data: response } = await api.get('/n8n/webhooks', { signal });
      if (!response || !Array.isArray(response.items) || !Number.isSafeInteger(response.total) || response.total < 0
        || (response.publishing_enabled !== undefined && typeof response.publishing_enabled !== 'boolean')
        || (response.supported_events !== undefined && (!Array.isArray(response.supported_events)
          || !response.supported_events.every((event: unknown) => typeof event === 'string')))) {
        throw new Error('Invalid webhook list');
      }
      return response;
    },
    retry: false,
  });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [events, setEvents] = useState('task.completed,device.online');
  const [webhookCreated, setWebhookCreated] = useState(false);
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle');
  const [deleteTarget, setDeleteTarget] = useState<WebhookItem | null>(null);
  const [operationStatus, setOperationStatus] = useState('');
  const createLock = useRef(false);
  const rowLock = useRef(false);
  const deleteTrigger = useRef<HTMLButtonElement | null>(null);
  const refreshButton = useRef<HTMLButtonElement | null>(null);
  const eventNames = events.split(',').map((event) => event.trim()).filter(Boolean);

  const createWebhook = useMutation({
    mutationFn: async () => {
      const { data: response } = await api.post('/n8n/webhooks', {
        name: name.trim(),
        url: url.trim(),
        events: eventNames,
      });
      return response as WebhookItem;
    },
    onSuccess: (response) => {
      setWebhookCreated(true);
      setCreatedSecret(response.secret);
      setCopyState('idle');
      setName(''); setUrl('');
      void qc.invalidateQueries({ queryKey });
    },
    onSettled: () => { createLock.current = false; },
  });
  const changeWebhook = useMutation({
    mutationFn: async (change: WebhookChange) => {
      const path = `/n8n/webhooks/${change.id}`;
      if (change.kind === 'delete') await api.delete(path);
      else await api.patch(path, { is_active: change.isActive });
    },
    onSuccess: async (_, change) => {
      await qc.invalidateQueries({ queryKey });
      const list = qc.getQueryState<WebhookListResponse>(queryKey);
      const current = list?.data?.items.find((webhook) => webhook.id === change.id);
      if (list?.status !== 'success') {
        setOperationStatus('Сервер принял изменение. Обновите список, чтобы сверить результат.');
      } else if (change.kind === 'delete' ? current : current?.is_active !== change.isActive) {
        setOperationStatus('Состояние вебхука изменилось. Проверьте текущие данные списка.');
      } else {
        setOperationStatus(change.kind === 'delete' ? 'Вебхук удалён.' : change.isActive ? 'Вебхук включён.' : 'Вебхук отключён.');
      }
      if (change.kind === 'delete') setDeleteTarget(null);
    },
    onSettled: () => { rowLock.current = false; },
  });

  const closeDialog = (open: boolean) => {
    if (!open && createLock.current) return;
    setDialogOpen(open);
    if (!open) { setWebhookCreated(false); setCreatedSecret(null); setCopyState('idle'); createWebhook.reset(); }
  };

  const copySecret = async () => {
    if (!createdSecret) return;
    try { await navigator.clipboard.writeText(createdSecret); setCopyState('copied'); }
    catch { setCopyState('error'); }
  };

  const submitChange = (change: WebhookChange) => {
    if (!canWrite || rowLock.current || isError) return;
    rowLock.current = true;
    setOperationStatus('');
    changeWebhook.mutate(change);
  };

  const closeDeleteDialog = () => {
    if (rowLock.current) return;
    setDeleteTarget(null);
    changeWebhook.reset();
  };

  const currentChange = changeWebhook.variables;
  const deletePending = changeWebhook.isPending && currentChange?.kind === 'delete';
  const deleteError = changeWebhook.isError && currentChange?.kind === 'delete';

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Интеграции и события"
        title="Вебхуки"
        description="Подписки на события и результаты доставки получателям."
        actions={section === 'subscriptions' && <>
          <Button ref={refreshButton} type="button" variant="outline" disabled={isFetching || changeWebhook.isPending} onClick={() => { void refetch(); }}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
            {isFetching ? 'Обновляем…' : 'Обновить'}
          </Button>
          {canWrite && <Dialog open={dialogOpen} onOpenChange={closeDialog}>
            <DialogTrigger asChild><Button><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Добавить вебхук</Button></DialogTrigger>
            <DialogContent aria-describedby={undefined}>
              <DialogHeader><DialogTitle>{webhookCreated ? 'Вебхук создан' : 'Новый вебхук'}</DialogTitle></DialogHeader>
              {webhookCreated ? (
                <div className="space-y-4 pt-2">
                  {createdSecret ? (
                    <>
                      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4"><p className="text-sm font-medium">Сохраните секрет сейчас</p><p className="mt-1 text-xs leading-5 text-muted-foreground">После закрытия этого окна секрет больше не будет показан. Не вставляйте его в публичные чаты и логи.</p></div>
                      <code className="block max-h-40 select-all overflow-auto break-all rounded-lg border border-border bg-muted/50 p-3 font-mono text-xs">{createdSecret}</code>
                      <Button type="button" variant="outline" onClick={() => { void copySecret(); }} disabled={copyState === 'copied'} className="w-full"><Copy className="mr-2 h-4 w-4" aria-hidden="true" />{copyState === 'copied' ? 'Секрет скопирован' : 'Скопировать секрет'}</Button>
                      {copyState === 'error' && <p role="alert" className="text-xs text-destructive">Браузер не разрешил копирование. Выделите значение выше и скопируйте вручную.</p>}
                    </>
                  ) : (
                    <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">Вебхук создан, но API не вернул секрет. Не отправляйте повторный запрос создания — проверьте секрет на стороне сервера.</div>
                  )}
                  <Button className="w-full" onClick={() => closeDialog(false)}><Check className="mr-2 h-4 w-4" aria-hidden="true" />Готово</Button>
                </div>
              ) : (
                <form className="space-y-4 pt-2" onSubmit={(event) => {
                  event.preventDefault();
                  if (!canWrite || createLock.current || !name.trim() || !url.trim() || !eventNames.length) return;
                  createLock.current = true;
                  createWebhook.mutate();
                }}>
                  <div className="space-y-2"><Label htmlFor="webhook-name">Название</Label><Input id="webhook-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="События автоматизации" autoComplete="off" /></div>
                  <div className="space-y-2"><Label htmlFor="webhook-url">URL получателя</Label><Input id="webhook-url" type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/webhook" autoComplete="url" /></div>
                  <div className="space-y-2"><Label htmlFor="webhook-events">События</Label><Input id="webhook-events" value={events} onChange={(event) => setEvents(event.target.value)} placeholder="task.completed, device.online" /><p className="text-xs text-muted-foreground">Список через запятую, например `task.completed,device.online`.</p></div>
                  {createWebhook.isError && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">Создание не подтверждено. Обновите реестр перед повтором.</p>}
                  <Button type="submit" disabled={createWebhook.isPending || !name.trim() || !url.trim() || !eventNames.length} className="w-full">{createWebhook.isPending ? 'Создаём…' : 'Создать вебхук'}</Button>
                </form>
              )}
            </DialogContent>
          </Dialog>}
        </>}
      />

      <Tabs value={section} onValueChange={value => {
        setHistorySubscription(null);
        setSection(value);
      }}>
        <TabsList aria-label="Разделы вебхуков">
          <TabsTrigger value="subscriptions">Подписки</TabsTrigger>
          <TabsTrigger value="deliveries">История доставки</TabsTrigger>
        </TabsList>
        <TabsContent value="deliveries" className="space-y-4 pt-3">
          {historySubscription && <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-card p-3">
            <p className="text-sm">Подписка «{historySubscription.name}»</p>
            <Button variant="outline" size="sm" onClick={() => setHistorySubscription(null)}>Все доставки</Button>
          </div>}
          <DeliveryHistory key={historySubscription?.id ?? 'all'} scope={scope} canReplay={canWrite} webhookId={historySubscription?.id} />
        </TabsContent>
        <TabsContent value="subscriptions" className="space-y-4 pt-3">
          {data && !isError && <Card><CardContent className="space-y-1 p-4 text-sm">
            <h2 className="font-medium">Публикация событий подписок</h2>
            <p className="text-muted-foreground">{data.publishing_enabled === true
              ? 'Публикация включена для разрешённых получателей.'
              : data.publishing_enabled === false ? 'Публикация подписок выключена на сервере. Настройки остаются доступными.'
                : 'Сервер не подтвердил состояние публикации подписок.'}</p>
            {!!data.supported_events?.length &&
              <p className="text-xs text-muted-foreground">События {data.supported_events.join(', ')}</p>}
          </CardContent></Card>}

      {operationStatus && <p role="status" className="text-sm text-muted-foreground">{operationStatus}</p>}
      {isError && (
        <Card><CardContent className="p-4">
          <p role="alert" className="text-sm text-destructive">
            {data ? 'Обновление не удалось. Показаны данные последнего успешного запроса. Обновите список перед изменением.' : 'Не удалось загрузить вебхуки. Повторите запрос кнопкой «Обновить».'}
          </p>
        </CardContent></Card>
      )}

      {isLoading && (
        <div className="space-y-3" aria-label="Загрузка вебхуков" aria-busy="true">{Array.from({ length: 3 }, (_, index) => <div key={index} className="h-32 animate-pulse rounded-xl border border-border bg-card motion-reduce:animate-none" />)}</div>
      )}
      {data && !data.items.length && !isError && (
        <Card><CardContent className="flex min-h-64 flex-col items-center justify-center p-8 text-center"><span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary"><WebhookIcon className="h-6 w-6" aria-hidden="true" /></span><p className="mt-4 font-semibold">Вебхуков пока нет</p>{canWrite && <Button className="mt-5" onClick={() => setDialogOpen(true)}><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Добавить вебхук</Button>}</CardContent></Card>
      )}
      {!!data?.items.length && (
        <section aria-label="Список вебхуков" className="space-y-3">
          <p className="text-xs text-muted-foreground">Всего вебхуков {data.total}</p>
          {data.items.map((webhook) => {
            const selectedToggle = currentChange?.kind === 'toggle' && currentChange.id === webhook.id ? currentChange : null;
            const pendingToggle = changeWebhook.isPending ? selectedToggle : null;
            const toggleError = selectedToggle && changeWebhook.isError;
            const toggleLabel = pendingToggle
              ? (pendingToggle.isActive ? 'Включаем…' : 'Отключаем…')
              : (webhook.is_active ? 'Отключить' : 'Включить');
            return (
              <Card key={webhook.id} className="shadow-soft">
                <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-start sm:justify-between sm:p-5">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><Radio className="h-5 w-5" aria-hidden="true" /></span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="font-semibold tracking-tight" id={`webhook-${webhook.id}`}>{webhook.name}</h2>
                        <Badge variant={webhook.is_active ? 'outline' : 'secondary'} className="rounded-full">{webhook.is_active ? 'Включён' : 'Отключён'}</Badge>
                      </div>
                      <p className="mt-1 max-w-3xl truncate font-mono text-xs text-muted-foreground" title={webhook.url}>{webhook.url}</p>
                      {webhook.receiver_allowed === false && <p className="mt-1 text-xs text-muted-foreground">Отправка на этот адрес не разрешена.</p>}
                      <div className="mt-2 flex flex-wrap gap-1.5">{webhook.events.map((event) => <Badge key={event} variant="outline" className="rounded-full text-[11px]">{event}</Badge>)}</div>
                      <DeliverySummary webhook={webhook} />
                      <p className="mt-2 text-[11px] text-muted-foreground">Создан {new Date(webhook.created_at).toLocaleString('ru-RU')}</p>
                      {toggleError && <p role="alert" className="mt-2 text-sm text-destructive">Изменение не подтверждено. Обновите список и проверьте состояние вебхука.</p>}
                    </div>
                  </div>
                  <div role="group" aria-labelledby={`webhook-${webhook.id}`} className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
                    <Button type="button" size="sm" variant="ghost" aria-label={`История доставки вебхука ${webhook.name}`} onClick={() => {
                      setHistorySubscription(webhook);
                      setSection('deliveries');
                    }}>История</Button>
                    {canWrite && <><Button type="button" size="sm" variant="outline" aria-label={`${toggleLabel} вебхук ${webhook.name}`} aria-busy={!!pendingToggle} disabled={isError || changeWebhook.isPending} onClick={() => submitChange({ id: webhook.id, kind: 'toggle', isActive: !webhook.is_active })}>
                      {toggleLabel}
                    </Button>
                    <Button type="button" size="icon" variant="ghost" className="h-9 w-9 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" aria-label={`Удалить вебхук ${webhook.name}`} disabled={isError || changeWebhook.isPending} onClick={(event) => {
                      deleteTrigger.current = event.currentTarget;
                      setDeleteTarget(webhook);
                    }}><Trash2 className="h-4 w-4" aria-hidden="true" /></Button></>}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </section>
      )}
      {canWrite && <Dialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) closeDeleteDialog(); }}>
        <DialogContent onCloseAutoFocus={(event) => {
          event.preventDefault();
          const previous = deleteTrigger.current;
          (previous?.isConnected ? previous : refreshButton.current)?.focus();
        }}>
          <DialogHeader>
            <DialogTitle>Удалить вебхук «{deleteTarget?.name}»?</DialogTitle>
            <DialogDescription>Подписка на события для этого получателя будет удалена.</DialogDescription>
          </DialogHeader>
          {deleteError && <p role="alert" className="text-sm text-destructive">Удаление не подтверждено. Закройте окно и обновите список.</p>}
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" disabled={deletePending} onClick={closeDeleteDialog}>Отмена</Button>
            <Button type="button" variant="destructive" disabled={isError || deletePending || deleteError} onClick={() => {
              if (deleteTarget) submitChange({ id: deleteTarget.id, kind: 'delete' });
            }}>{deletePending ? 'Удаляем…' : 'Удалить вебхук'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>}
        </TabsContent>
      </Tabs>
    </PageFrame>
  );
}
