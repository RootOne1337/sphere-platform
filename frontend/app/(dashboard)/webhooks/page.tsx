'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, Copy, Plus, Radio, Trash2, Webhook as WebhookIcon } from 'lucide-react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';

interface WebhookItem {
  id: string;
  name: string;
  url: string;
  events: string[];
  tags: string[];
  is_active: boolean;
  secret: string | null;
  created_at: string;
}

interface WebhookListResponse { items: WebhookItem[]; total: number; }

export default function WebhooksPage() {
  const qc = useQueryClient();
  const { data, isLoading, isError, refetch } = useQuery<WebhookListResponse>({
    queryKey: ['webhooks'],
    queryFn: async () => {
      const { data: response } = await api.get('/n8n/webhooks');
      return response;
    },
  });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [events, setEvents] = useState('task.completed,device.online');
  const [webhookCreated, setWebhookCreated] = useState(false);
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle');

  const createWebhook = useMutation({
    mutationFn: async () => {
      const { data: response } = await api.post('/n8n/webhooks', {
        name: name.trim(),
        url: url.trim(),
        events: events.split(',').map((event) => event.trim()).filter(Boolean),
      });
      return response as WebhookItem;
    },
    onSuccess: (response) => {
      setWebhookCreated(true);
      setCreatedSecret(response.secret);
      setCopyState('idle');
      setName(''); setUrl('');
      void qc.invalidateQueries({ queryKey: ['webhooks'] });
    },
  });
  const deleteWebhook = useMutation({ mutationFn: (id: string) => api.delete(`/n8n/webhooks/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ['webhooks'] }) });
  const toggleWebhook = useMutation({
    mutationFn: async ({ id, isActive }: { id: string; isActive: boolean }) => { await api.patch(`/n8n/webhooks/${id}`, { is_active: isActive }); },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['webhooks'] }),
  });

  const closeDialog = (open: boolean) => {
    setDialogOpen(open);
    if (!open) { setWebhookCreated(false); setCreatedSecret(null); setCopyState('idle'); createWebhook.reset(); }
  };

  const copySecret = async () => {
    if (!createdSecret) return;
    try { await navigator.clipboard.writeText(createdSecret); setCopyState('copied'); }
    catch { setCopyState('error'); }
  };

  const mutationError = createWebhook.isError || deleteWebhook.isError || toggleWebhook.isError;

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Интеграции и события"
        title="Вебхуки"
        description="Передавайте события Sphere во внешние обработчики. Секрет нового вебхука отображается только сразу после создания."
        actions={(
          <Dialog open={dialogOpen} onOpenChange={closeDialog}>
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
                <form className="space-y-4 pt-2" onSubmit={(event) => { event.preventDefault(); createWebhook.mutate(); }}>
                  <div className="space-y-2"><Label htmlFor="webhook-name">Название</Label><Input id="webhook-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="События автоматизации" autoComplete="off" /></div>
                  <div className="space-y-2"><Label htmlFor="webhook-url">URL получателя</Label><Input id="webhook-url" type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/webhook" autoComplete="url" /></div>
                  <div className="space-y-2"><Label htmlFor="webhook-events">События</Label><Input id="webhook-events" value={events} onChange={(event) => setEvents(event.target.value)} placeholder="task.completed, device.online" /><p className="text-xs text-muted-foreground">Список через запятую, например `task.completed,device.online`.</p></div>
                  {createWebhook.isError && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">Не удалось создать вебхук. Проверьте URL и права доступа.</p>}
                  <Button type="submit" disabled={createWebhook.isPending || !name.trim() || !url.trim() || !events.trim()} className="w-full">{createWebhook.isPending ? 'Создаём…' : 'Создать вебхук'}</Button>
                </form>
              )}
            </DialogContent>
          </Dialog>
        )}
      />

      {mutationError && <div role="alert" className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />Операция не выполнена. Проверьте журнал событий и права интеграции.</div>}

      {isError ? (
        <Card><CardContent className="flex flex-col gap-3 p-6 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-medium">Не удалось загрузить вебхуки</p><p className="mt-1 text-sm text-muted-foreground">Проверьте доступность API и повторите запрос.</p></div><Button type="button" variant="outline" onClick={() => { void refetch(); }}>Повторить</Button></CardContent></Card>
      ) : isLoading ? (
        <div className="space-y-3" aria-label="Загрузка вебхуков" aria-busy="true">{Array.from({ length: 3 }, (_, index) => <div key={index} className="h-32 animate-pulse rounded-xl border border-border bg-card motion-reduce:animate-none" />)}</div>
      ) : !data?.items.length ? (
        <Card><CardContent className="flex min-h-64 flex-col items-center justify-center p-8 text-center"><span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary"><WebhookIcon className="h-6 w-6" aria-hidden="true" /></span><p className="mt-4 font-semibold">Вебхуков пока нет</p><p className="mt-1 max-w-md text-sm text-muted-foreground">Создайте endpoint, чтобы передавать подтверждённые события Sphere во внешнюю систему.</p><Button className="mt-5" onClick={() => setDialogOpen(true)}><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Добавить вебхук</Button></CardContent></Card>
      ) : (
        <section aria-label="Список вебхуков" className="space-y-3">
          <p className="text-xs text-muted-foreground">{data.total} {data.total === 1 ? 'интеграция' : 'интеграций'} · секреты не отображаются в списке</p>
          {data.items.map((webhook) => (
            <Card key={webhook.id} className="shadow-soft transition-[border-color,box-shadow] duration-200 hover:border-primary/30 hover:shadow-md motion-reduce:transition-none">
              <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
                <div className="flex min-w-0 items-start gap-3"><span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><Radio className="h-5 w-5" aria-hidden="true" /></span><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold tracking-tight">{webhook.name}</h2><Badge variant={webhook.is_active ? 'success' : 'secondary'} className="rounded-full">{webhook.is_active ? 'Активен' : 'Отключён'}</Badge></div><p className="mt-1 max-w-3xl truncate font-mono text-xs text-muted-foreground" title={webhook.url}>{webhook.url}</p><div className="mt-2 flex flex-wrap gap-1.5">{webhook.events.map((event) => <Badge key={event} variant="outline" className="rounded-full text-[11px]">{event}</Badge>)}</div><p className="mt-2 text-[11px] text-muted-foreground">Создан {new Date(webhook.created_at).toLocaleString('ru-RU')}</p></div></div>
                <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end"><Button type="button" size="sm" variant="outline" onClick={() => toggleWebhook.mutate({ id: webhook.id, isActive: !webhook.is_active })} disabled={toggleWebhook.isPending}>{webhook.is_active ? 'Отключить' : 'Включить'}</Button><Button type="button" size="icon" variant="ghost" className="h-9 w-9 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" aria-label={`Удалить вебхук ${webhook.name}`} disabled={deleteWebhook.isPending} onClick={() => { if (window.confirm(`Удалить вебхук «${webhook.name}»?`)) deleteWebhook.mutate(webhook.id); }}><Trash2 className="h-4 w-4" aria-hidden="true" /></Button></div>
              </CardContent>
            </Card>
          ))}
        </section>
      )}
    </PageFrame>
  );
}
