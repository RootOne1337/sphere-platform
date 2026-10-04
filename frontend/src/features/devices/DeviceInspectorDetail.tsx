'use client';

import { useRef, useState } from 'react';
import Link from 'next/link';
import { Camera, Code2, ExternalLink, FileText, MonitorPlay, RefreshCw, Terminal } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { useDeviceSnapshot } from '@/lib/hooks/useDeviceSnapshot';
import { Button } from '@/src/shared/ui/button';
import { Badge } from '@/src/shared/ui/badge';
import { DeviceStatusBadge } from '@/components/sphere/DeviceStatusBadge';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { SingleDeviceStream } from '@/src/features/stream/SingleDeviceStream';
import { WebTerminal } from './WebTerminal';
import { LogcatViewer } from './LogcatViewer';
import { RunScriptTab } from './RunScriptTab';
import { DEVICE_COMMAND_TIMEOUT } from './interactiveResult';
import { NativeScreenshotPanel } from './NativeScreenshotPanel';
import { AndroidProfilePanel } from './AndroidProfilePanel';
import { DeviceDiagnosticsPanel, DeviceHistoryPanel, DeviceSavedLogsPanel, Metric, utcTime } from './DeviceOperationsPanels';
import { useCapabilities } from '@/src/features/access/Capabilities';

type View = 'summary' | 'tasks' | 'events' | 'diagnostics' | 'logs' | 'stream' | 'terminal' | 'logcat' | 'script' | 'screenshot' | 'profile';
const VIEWS = [['summary', 'Обзор'], ['tasks', 'Задачи'], ['events', 'События'], ['diagnostics', 'Видео'], ['logs', 'Логи APK']] as const;

function reportedNumber(value: unknown, suffix: string, max = Infinity): string {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= max ? `${value.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}${suffix}` : 'Не сообщено';
}
function elapsed(value: unknown): string {
  if (typeof value !== 'string') return 'Начало сессии не сообщено';
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp) || timestamp > Date.now() + 60_000) return 'Начало сессии не сообщено';
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  return `${Math.floor(seconds / 3600)} ч ${Math.floor(seconds % 3600 / 60)} мин ${seconds % 60} с`;
}

export function DeviceInspectorDetail({ deviceId, fullPage = false }: { deviceId: string; fullPage?: boolean }) {
  const access = useCapabilities();
  const canWrite = access.can('device:write');
  const canViewStream = access.can('stream:read');
  const query = useDeviceSnapshot(deviceId);
  const device = query.data;
  const [view, setView] = useState<View>('summary');
  const [rebootOpen, setRebootOpen] = useState(false);
  const [rebootPending, setRebootPending] = useState(false);
  const commandLock = useRef(false);
  const isReachable = !!device && query.isFetchedAfterMount && !query.isError && Date.now() - query.dataUpdatedAt <= 45_000 && ['online', 'busy'].includes(device.status);

  const reboot = async () => {
    if (!canWrite || !isReachable || commandLock.current) return;
    commandLock.current = true;
    setRebootPending(true);
    try {
      const { data } = await api.post(`/devices/${encodeURIComponent(deviceId)}/reboot`, undefined, { timeout: DEVICE_COMMAND_TIMEOUT.reboot });
      if (data?.status !== 'reboot_initiated' || data?.device_id !== deviceId) throw new Error('Неподтверждённый ответ команды.');
      toast.success('Команда перезагрузки принята', { description: 'Фактическое восстановление связи проверяется по следующим heartbeat.' });
      setRebootOpen(false);
      void query.refetch();
    } catch (error) {
      toast.error('Не удалось подтвердить перезагрузку', { description: getApiErrorMessage(error, 'Результат неизвестен. Проверьте состояние устройства перед повтором.') });
    } finally {
      commandLock.current = false;
      setRebootPending(false);
    }
  };

  if (!device && query.isLoading) return <p role="status" className="p-4 text-sm text-muted-foreground">Загрузка карточки устройства…</p>;
  if (!device) return <div role="alert" className="space-y-3 rounded-xl border border-destructive/30 p-4"><h3 className="font-semibold">Карточка устройства недоступна</h3><p className="text-sm text-muted-foreground">API не вернул подтверждённые данные для выбранного ID. Проверьте доступ и существование записи.</p><Button variant="outline" disabled={query.isFetching} onClick={() => { void query.refetch(); }}>Повторить запрос</Button></div>;

  return <div className="min-w-0 space-y-5">
    <header className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h3 className="break-words text-xl font-semibold tracking-tight">{device.name}</h3><p className="mt-1 text-sm text-muted-foreground">{device.device_model || device.model || 'Модель не сообщена'} · Android {device.android_version || 'не сообщён'}</p></div><DeviceStatusBadge status={device.status} /></div>
      <div className="flex flex-wrap items-center gap-2"><Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => { void query.refetch(); }}><RefreshCw className="mr-2 h-4 w-4" aria-hidden />Обновить карточку</Button>{!fullPage && <Button asChild variant="ghost" size="sm"><Link href={`/devices/${encodeURIComponent(deviceId)}`}><ExternalLink className="mr-2 h-4 w-4" aria-hidden />Полная карточка</Link></Button>}</div>
      <p className="text-xs text-muted-foreground">Запрос API: {utcTime(new Date(query.dataUpdatedAt).toISOString())} · опрос каждые 15 секунд.</p>
      {query.isError && <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">Обновление карточки не удалось. Показан сохранённый ответ; управление заблокировано до успешной проверки.</p>}
    </header>
    <Tabs value={VIEWS.some(([key]) => key === view) ? view : 'summary'} onValueChange={(value) => setView(value as View)}>
      <TabsList aria-label="Разделы карточки устройства" className="grid h-auto w-full grid-cols-3 gap-1 bg-muted/50 p-1 sm:grid-cols-5">{VIEWS.map(([key, label]) => <TabsTrigger key={key} value={key} className="min-w-0 px-2 py-2 text-xs">{label}</TabsTrigger>)}</TabsList>
      <TabsContent value="summary" className="mt-5 space-y-5">
        {!VIEWS.some(([key]) => key === view) ? <>
          <Button variant="outline" size="sm" onClick={() => setView('summary')}>Назад к обзору</Button>
          {view === 'stream' && canViewStream && <SingleDeviceStream key={deviceId} deviceId={deviceId} />}
          {view === 'terminal' && canWrite && <div className="h-[480px] min-w-0"><WebTerminal deviceId={deviceId} enabled={isReachable} /></div>}
          {view === 'logcat' && access.can('device:read') && <div className="h-[480px] min-w-0"><LogcatViewer deviceId={deviceId} enabled={isReachable} /></div>}
          {view === 'script' && canWrite && <RunScriptTab deviceId={deviceId} deviceName={device.name} isOnline={isReachable} onBack={() => setView('summary')} />}
          {view === 'screenshot' && canWrite && <NativeScreenshotPanel key={deviceId} deviceId={deviceId} enabled={isReachable} />}
          {view === 'profile' && canWrite && <AndroidProfilePanel key={deviceId} deviceId={deviceId} enabled={isReachable} />}
        </> : <>
          <dl className={`grid grid-cols-2 gap-3 ${fullPage ? 'lg:grid-cols-4' : ''}`}>
            <Metric label="Sphere Agent" value={device.agent_version ? `${device.agent_version}${device.agent_version_code ? ` / ${device.agent_version_code}` : ''}` : 'Версия не сообщена'} />
            <Metric label="Длительность текущей связи" value={['online', 'busy'].includes(device.status) ? elapsed(device.connected_since) : 'Нет подтверждённой активной связи'} />
            <Metric label="Последний heartbeat APK" value={utcTime(device.last_heartbeat)} />
            <Metric label="Последний контакт в каталоге" value={utcTime(device.last_seen)} />
            <Metric label="CPU" value={reportedNumber(device.cpu_usage, '%', 100)} />
            <Metric label="RAM" value={reportedNumber(device.ram_usage_mb, ' MB')} />
            <Metric label="Заряд" value={reportedNumber(device.battery_level, '%', 100)} />
            <Metric label="Экран Android" value={typeof device.screen_on === 'boolean' ? device.screen_on ? 'Включён' : 'Выключен' : 'Не сообщено'} />
          </dl>
          <section aria-label="Управление устройством" className="space-y-3 rounded-xl border border-border p-4">
            <h4 className="text-sm font-semibold">Управление устройством</h4>
            <p className="text-xs text-muted-foreground">Статус heartbeat не гарантирует видеокадр или исполнение команды. Результат проверяется отдельно.</p>
            {!canWrite && <p role="status" className="text-xs text-muted-foreground">Роль не разрешает терминал, shell-скрипты и перезагрузку. Просмотр доступен согласно правам API.</p>}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <Button variant="outline" disabled={!isReachable || !canViewStream} onClick={() => setView('stream')}><MonitorPlay className="mr-2 h-4 w-4" aria-hidden />Видеопоток</Button>
              <Button variant="outline" disabled={!isReachable || !canWrite} onClick={() => setView('terminal')}><Terminal className="mr-2 h-4 w-4" aria-hidden />Терминал</Button>
              <Button variant="outline" disabled={!isReachable || !access.can('device:read')} onClick={() => setView('logcat')}><FileText className="mr-2 h-4 w-4" aria-hidden />Logcat</Button>
              <Button variant="outline" disabled={!isReachable || !canWrite} onClick={() => setView('script')}><Code2 className="mr-2 h-4 w-4" aria-hidden />Shell-скрипт</Button>
              <Button variant="outline" disabled={!isReachable || !canWrite} onClick={() => setView('screenshot')}><Camera className="mr-2 h-4 w-4" aria-hidden />Снимок экрана</Button>
              <Button variant="outline" disabled={!canWrite || !isReachable || rebootPending} onClick={() => setRebootOpen(true)}><RefreshCw className="mr-2 h-4 w-4" aria-hidden />Перезагрузка</Button>
            </div>
            {!isReachable && <p className="text-xs text-muted-foreground">Живые команды недоступны при этом состоянии. Сохранённые задачи, события и логи можно проверить во вкладках.</p>}
          </section>
          <section className="space-y-3 rounded-xl border border-border p-4"><div className="flex flex-wrap items-center justify-between gap-3"><h4 className="text-sm font-semibold">Идентификация и доступ</h4><Button variant="outline" disabled={!canWrite || !isReachable} onClick={() => setView('profile')}>Системный профиль Android</Button></div><dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Metric label="ID Sphere" value={<span className="break-all font-mono text-xs">{device.id}</span>} />
            <Metric label={device.android_id ? 'Android ID' : 'Серийный идентификатор'} value={<span className="break-all font-mono text-xs">{device.android_id || device.serial || 'Не сообщён'}</span>} />
            <Metric label="ADB (дополнительный канал)" value={typeof device.adb_connected === 'boolean' ? device.adb_connected ? 'Подключён' : 'Не подключён' : 'Не сообщено'} />
            <Metric label="VPN, активность по APK" value={typeof device.vpn_active === 'boolean' ? device.vpn_active ? 'Активен' : 'Не активен' : 'Не сообщено'} />
            <Metric label="Группы" value={device.group_name || device.group_ids?.join(', ') || 'Не назначены'} />
            <Metric label="Локации" value={device.location_ids?.join(', ') || 'Не назначены'} />
            <Metric label="Игровой сервер" value={device.server_name || 'Не назначен'} />
            <Metric label="Создано" value={utcTime(device.created_at)} /><Metric label="Изменено" value={utcTime(device.updated_at)} />
          </dl>{device.notes && <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">{device.notes}</p>}{!!device.tags?.length && <div className="flex flex-wrap gap-2">{device.tags.map((tag) => <Badge key={tag} variant="outline" className="max-w-full break-all">{tag}</Badge>)}</div>}<Button asChild variant="outline" size="sm"><Link href="/devices">Переименование, группы и удаление в реестре</Link></Button></section>
        </>}
      </TabsContent>
      <TabsContent value="tasks" className="mt-5"><DeviceHistoryPanel deviceId={deviceId} kind="tasks" /></TabsContent>
      <TabsContent value="events" className="mt-5"><DeviceHistoryPanel deviceId={deviceId} kind="events" /></TabsContent>
      <TabsContent value="diagnostics" className="mt-5"><DeviceDiagnosticsPanel deviceId={deviceId} /></TabsContent>
      <TabsContent value="logs" className="mt-5"><DeviceSavedLogsPanel deviceId={deviceId} /></TabsContent>
    </Tabs>
    <Dialog open={rebootOpen} onOpenChange={(open) => { if (!rebootPending) setRebootOpen(open); }}><DialogContent className="w-[calc(100%-2rem)] rounded-xl"><DialogHeader><DialogTitle>Перезагрузить «{device.name}»?</DialogTitle><DialogDescription>Android временно потеряет связь и остановит текущую работу. Принятие команды не подтверждает завершение перезагрузки.</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" disabled={rebootPending} onClick={() => setRebootOpen(false)}>Отмена</Button><Button variant="destructive" disabled={!canWrite || !isReachable || rebootPending} onClick={() => { void reboot(); }}>{rebootPending ? 'Ожидаем ответ…' : 'Подтвердить перезагрузку'}</Button></DialogFooter></DialogContent></Dialog>
  </div>;
}
