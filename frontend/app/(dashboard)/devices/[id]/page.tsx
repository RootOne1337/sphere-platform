'use client';

import { use, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { AlertTriangle, ArrowLeft, Clock3, Monitor, RefreshCw, Smartphone, Trash2, Wifi, Zap } from 'lucide-react';
import { api } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';

interface Props { params: Promise<{ id: string }>; }
interface DeviceDetail {
  id: string;
  name: string;
  android_id: string;
  model: string;
  android_version: string;
  tags?: string[] | null;
  group_id: string | null;
  group_name: string | null;
  status: string;
  battery_level: number | null;
  last_seen: string | null;
  adb_connected: boolean;
  vpn_assigned: boolean;
  created_at: string;
  updated_at: string;
}

function humanStatus(status: string | null | undefined) {
  switch ((status ?? '').toLowerCase()) {
    case 'online': return 'В сети';
    case 'busy': return 'Выполняет задачу';
    case 'connecting': return 'Подключается';
    case 'offline': return 'Не в сети';
    case 'error': return 'Ошибка';
    default: return status || 'Неизвестно';
  }
}

function statusVariant(status: string | null | undefined): 'success' | 'warning' | 'destructive' | 'secondary' | 'outline' {
  switch ((status ?? '').toLowerCase()) {
    case 'online': return 'success';
    case 'busy': case 'connecting': return 'warning';
    case 'error': return 'destructive';
    case 'offline': return 'secondary';
    default: return 'outline';
  }
}

function formatTimestamp(value: string | null) {
  if (!value) return 'Нет данных';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' });
}

function DetailRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="flex min-w-0 items-start justify-between gap-4 border-b border-border/60 py-2.5 last:border-0"><dt className="shrink-0 text-sm text-muted-foreground">{label}</dt><dd className={`min-w-0 truncate text-right text-sm font-medium ${mono ? 'font-mono text-xs' : ''}`} title={value}>{value}</dd></div>;
}

export default function DeviceDetailPage({ params }: Props) {
  const { id } = use(params);
  const router = useRouter();
  const qc = useQueryClient();
  const [deleteError, setDeleteError] = useState(false);

  const { data: device, isLoading, isError, refetch } = useQuery<DeviceDetail>({
    queryKey: ['devices', id],
    queryFn: async () => {
      const { data } = await api.get(`/devices/${encodeURIComponent(id)}`);
      return data;
    },
  });

  const connectAdb = useMutation({
    mutationFn: () => api.post(`/devices/${encodeURIComponent(id)}/connect`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices', id] }),
  });
  const deleteDevice = useMutation({
    mutationFn: () => api.delete(`/devices/${encodeURIComponent(id)}`),
    onSuccess: async () => {
      setDeleteError(false);
      await qc.invalidateQueries({ queryKey: ['devices'] });
      router.push('/devices');
    },
    onError: () => setDeleteError(true),
  });

  if (isLoading) {
    return <PageFrame><div aria-label="Загрузка устройства" aria-busy="true" className="space-y-5"><div className="h-24 animate-pulse rounded-2xl border border-border bg-card motion-reduce:animate-none" /><div className="grid gap-4 md:grid-cols-3">{Array.from({ length: 3 }, (_, index) => <div key={index} className="h-64 animate-pulse rounded-xl border border-border bg-card motion-reduce:animate-none" />)}</div></div></PageFrame>;
  }

  if (isError || !device) {
    return <PageFrame><PageHeading eyebrow="Каталог Sphere" title="Устройство недоступно" description="Не удалось получить подтверждённую карточку устройства." actions={<Button asChild variant="outline"><Link href="/devices"><ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />К реестру</Link></Button>} /><Card><CardContent className="flex flex-col gap-3 p-6 sm:flex-row sm:items-center sm:justify-between"><p className="text-sm text-muted-foreground">Проверьте идентификатор или доступность API.</p><Button type="button" onClick={() => { void refetch(); }}><RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />Повторить</Button></CardContent></Card></PageFrame>;
  }

  const normalizedStatus = (device.status ?? 'unknown').toLowerCase();
  const tags = device.tags ?? [];

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Карточка устройства"
        title={device.name || 'Android-устройство'}
        description={`Идентификатор устройства · ${device.id}`}
        actions={<><Button asChild variant="outline"><Link href={`/stream/${encodeURIComponent(device.id)}`}><Monitor className="mr-2 h-4 w-4" aria-hidden="true" />Открыть поток</Link></Button><Button asChild variant="ghost"><Link href="/devices"><ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />Реестр</Link></Button></>}
      />

      {(connectAdb.isError || deleteError) && <div role="alert" className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />{deleteError ? 'Не удалось удалить устройство. Запись оставлена без изменений.' : 'Не удалось подключить ADB. Проверьте маршрут и права устройства.'}</div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="overflow-hidden shadow-soft xl:col-span-7">
          <CardHeader className="border-b border-border/70 bg-muted/30 p-5 sm:p-6"><CardTitle className="flex items-center gap-3 font-sans text-base font-semibold"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary"><Smartphone className="h-5 w-5" aria-hidden="true" /></span>Сведения об устройстве</CardTitle></CardHeader>
          <CardContent className="p-5 sm:p-6">
            <dl className="grid grid-cols-1 gap-x-10 gap-y-0 md:grid-cols-2">
              <DetailRow label="Модель" value={device.model || 'Не сообщена'} />
              <DetailRow label="Версия Android" value={device.android_version || 'Не сообщена'} />
              <DetailRow label="Android ID" value={device.android_id || '—'} mono />
              <DetailRow label="Группа" value={device.group_name || 'Не назначена'} />
              <DetailRow label="Создано" value={formatTimestamp(device.created_at)} />
              <DetailRow label="Изменено" value={formatTimestamp(device.updated_at)} />
            </dl>
            {tags.length > 0 && <div className="mt-5 border-t border-border/70 pt-4"><p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Метки</p><div className="flex flex-wrap gap-2">{tags.map((tag) => <Badge key={tag} variant="outline" className="rounded-full">{tag}</Badge>)}</div></div>}
          </CardContent>
        </Card>

        <Card className="overflow-hidden shadow-soft xl:col-span-5">
          <CardHeader className="border-b border-border/70 bg-muted/30 p-5 sm:p-6"><CardTitle className="flex items-center gap-3 font-sans text-base font-semibold"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary"><Wifi className="h-5 w-5" aria-hidden="true" /></span>Состояние и доступ</CardTitle></CardHeader>
          <CardContent className="space-y-4 p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/70 bg-background p-4"><div><p className="text-xs text-muted-foreground">Состояние по API</p><p className="mt-1 text-sm font-medium">{humanStatus(device.status)}</p></div><Badge variant={statusVariant(device.status)} className="rounded-full px-3">{normalizedStatus}</Badge></div>
            <dl>
              <DetailRow label="Заряд" value={device.battery_level != null ? `${device.battery_level}%` : 'Нет данных'} />
              <DetailRow label="Последний heartbeat" value={formatTimestamp(device.last_seen)} />
              <DetailRow label="ADB" value={device.adb_connected ? 'Подключён' : 'Не подключён'} />
              <DetailRow label="VPN" value={device.vpn_assigned ? 'Назначен' : 'Не назначен'} />
            </dl>
            <div className="grid grid-cols-2 gap-2 border-t border-border/70 pt-4">
              <Button type="button" variant="outline" onClick={() => connectAdb.mutate()} disabled={connectAdb.isPending || device.adb_connected} className="w-full"><Zap className="mr-2 h-4 w-4" aria-hidden="true" />{connectAdb.isPending ? 'Подключаем…' : device.adb_connected ? 'ADB подключён' : 'Подключить ADB'}</Button>
              <Button type="button" variant="destructive" onClick={() => { setDeleteError(false); if (window.confirm(`Удалить устройство «${device.name}» из каталога?`)) deleteDevice.mutate(); }} disabled={deleteDevice.isPending} className="w-full"><Trash2 className="mr-2 h-4 w-4" aria-hidden="true" />{deleteDevice.isPending ? 'Удаляем…' : 'Удалить'}</Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="shadow-soft">
        <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-start gap-3"><Clock3 className="mt-0.5 h-4 w-4 text-muted-foreground" aria-hidden="true" /><div><p className="text-sm font-medium">Снимок данных</p><p className="mt-1 text-xs text-muted-foreground">Показаны поля, сообщённые API. Отсутствующее значение обозначено как «нет данных».</p></div></div><Button type="button" variant="outline" size="sm" onClick={() => { void refetch(); }}><RefreshCw className="mr-2 h-3.5 w-3.5" aria-hidden="true" />Обновить</Button></CardContent>
      </Card>
    </PageFrame>
  );
}
