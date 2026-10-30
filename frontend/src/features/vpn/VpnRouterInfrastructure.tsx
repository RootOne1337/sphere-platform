'use client';

import { useState, useMemo, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Network, Activity, Settings, Plus, Lock, RotateCcw, FileText, Wrench, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogBody,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { DeviceSearchSelect } from '@/components/sphere/DeviceSearchSelect';

import { useVpnPeers, usePoolStats, useAssignVpn } from '@/lib/hooks/useVpn';
import { useAuthStore } from '@/lib/store';
import { VpnControlDialog, vpnActorScope } from '@/src/features/vpn/VpnControlDialog';
import { controlFailure, type ControlOutcome, type VpnControl } from '@/src/features/vpn/controlReceipt';

interface Tunnel {
  id: string;
  deviceId: string;
  name: string;
  endpoint: string | null;
  status: string;
  active: boolean;
  lastHandshakeAt: string | null;
}

function formatHandshake(value: string | null): string {
  if (!value) return 'Не сообщено';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'Время не подтверждено' : `${date.toISOString().replace('T', ' ').slice(0, 19)} UTC`;
}

export function VpnRouterInfrastructure() {
  const router = useRouter();
  const actor = useAuthStore(s => s.user); const session = useAuthStore(s => s.sessionVersion);
  const scope = `${actor?.org_id}:${actor?.id}:${actor?.role}:${session}`;
  const canVpn = Boolean(actor && ['org_admin', 'org_owner', 'super_admin'].includes(actor.role));
  const canReboot = canVpn || actor?.role === 'device_manager';
  const [operation, setOperation] = useState<{ kind: VpnControl; ids: string[]; scope: string } | null>(null);
  const [outcomes, setOutcomes] = useState<{ scope: string; rows: ControlOutcome[] }>({ scope, rows: [] });
  const unresolved = new Set(outcomes.scope === scope ? outcomes.rows.filter(v => v.outcome === 'unknown').map(v => v.deviceId) : []);
  const provisionBusy = useRef(false);
  const [provisionDone, setProvisionDone] = useState(false);
  const [provisionNotice, setProvisionNotice] = useState<string | null>(null);
  const [provisionScope, setProvisionScope] = useState<string | null>(null);
  const query = useVpnPeers();
  const fresh = !query.isLoading && !query.isError && !query.isFetching && Array.isArray(query.data);
  const openOperation = (kind: VpnControl, ids: string[]) => {
    if (!fresh || !ids.length || ids.length > 500 || ids.some(id => unresolved.has(id)) || (kind === 'reboot' ? !canReboot : !canVpn)) return;
    setOperation({ kind, ids: [...new Set(ids)], scope });
  };
  const [search, setSearch] = useState('');

  // Диалоги
  const [policyDialogOpen, setPolicyDialogOpen] = useState(false);
  const [provisionDialogOpen, setProvisionDialogOpen] = useState(false);
  const [configureDialogOpen, setConfigureDialogOpen] = useState<string | null>(null); // peer id
  const [provisionDeviceId, setProvisionDeviceId] = useState('');
  const [provisionError, setProvisionError] = useState<string | null>(null);

  // Используем хук вместо инлайн-запроса для единообразия и корректного кеширования
  const { data: rawPeers = [], isLoading, isError: peersError } = query;
  const { data: poolStats, isLoading: poolStatsLoading, isError: poolStatsError } = usePoolStats();
  const assignVpn = useAssignVpn();

  const peerDeviceIds = useMemo(
    () => new Set(rawPeers.flatMap((peer) => peer.device_id ? [peer.device_id] : [])),
    [rawPeers],
  );

  const tunnels: Tunnel[] = useMemo(() => rawPeers
    .filter((peer) => peer.device_id !== null && peer.status !== 'free')
    .map((peer) => ({
      id: peer.id,
      deviceId: peer.device_id!,
      name: `Device ${peer.device_id!.slice(0, 8)}`,
      endpoint: peer.assigned_ip,
      status: peer.status === 'assigned' && peer.is_active ? 'ACTIVE' : peer.status.toUpperCase(),
      active: peer.status === 'assigned' && peer.is_active,
      lastHandshakeAt: peer.last_handshake_at,
    })), [rawPeers]);
  const visibleTunnels = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    if (!normalizedSearch) return tunnels;
    return tunnels.filter((tunnel) =>
      tunnel.name.toLowerCase().includes(normalizedSearch)
      || tunnel.deviceId.toLowerCase().includes(normalizedSearch)
      || tunnel.id.toLowerCase().includes(normalizedSearch)
      || (tunnel.endpoint ?? '').toLowerCase().includes(normalizedSearch),
    );
  }, [search, tunnels]);
  const activeTunnelCount = tunnels.filter((tunnel) => tunnel.active).length;
  const attentionTunnelCount = tunnels.length - activeTunnelCount;

  return (
    <div className="flex min-w-0 flex-col rounded-2xl border bg-card/50">
      {/* Header Area */}
      <div className="px-5 py-5 border-b border-border shrink-0">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Network className="w-5 h-5 text-primary" />
              <h2 className="text-lg font-semibold tracking-tight text-foreground">Инфраструктура VPN</h2>
            </div>
            <p className="text-sm text-muted-foreground max-w-2xl">
              Адресный пул, назначения устройств и состояние пиров маршрутизатора.
            </p>
          </div>

          <div className="flex min-w-0 items-center bg-background/50 p-3 rounded-xl border border-border">
            <div className="grid min-w-0 grid-cols-3 gap-3">
              <div className="flex flex-col">
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <Lock className="w-3 h-3" /> Назначено
                </span>
                <span className="text-xl text-foreground font-semibold">{poolStatsLoading ? '…' : poolStatsError ? 'Нет данных' : poolStats?.allocated ?? '—'}</span>
              </div>
              <div className="flex min-w-0 flex-col border-l border-border pl-3">
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3" /> Handshake
                </span>
                <span className="text-xl text-success font-semibold">{activeTunnelCount}</span>
              </div>
              <div className="flex min-w-0 flex-col border-l border-border pl-3">
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" /> Нет handshake
                </span>
                <span className="text-xl text-warning font-semibold">{attentionTunnelCount}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="p-4 sm:p-5 flex-1 min-w-0">
        <p className="mb-4 rounded-xl border border-warning/20 bg-warning/5 px-4 py-3 text-xs leading-relaxed">Назначение адреса на маршрутизаторе не включает VPN на Android. Фактическое состояние сервиса проверяйте в подключениях устройств.</p>
        {unresolved.size > 0 && <p role="alert" className="mb-4 rounded-lg border border-destructive/40 p-3 text-sm">{unresolved.size} устройств с неизвестным результатом. Новые операции для них заблокированы в этой сессии страницы; нужна сверка состояния.</p>}
        {outcomes.scope === scope && outcomes.rows.length > 0 && <section aria-label="Последние результаты VPN" className="mb-4 grid gap-3 md:grid-cols-2">{outcomes.rows.map(row => <article key={row.deviceId} className="rounded-lg border p-3 text-sm"><p className="break-all font-mono text-xs">{row.deviceId}</p><p>{row.outcome} · {row.detail}</p></article>)}</section>}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-3">
            <Input
              placeholder="Поиск устройства, peer или адреса…"
              className="w-full sm:w-72 h-10 bg-background/50 border-border text-sm focus-visible:ring-primary/50"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-3">
            <Button variant="outline" size="sm" className="h-9 border-border hover:bg-border" onClick={() => setPolicyDialogOpen(true)}>
              <Settings className="w-4 h-4 mr-2" /> Политики
            </Button>
            <Button variant="default" size="sm" className="h-9" disabled={!canVpn || !fresh} onClick={() => {
              setProvisionScope(scope); setProvisionDone(false); setProvisionNotice(null);
              setProvisionDeviceId('');
              setProvisionError(null);
              setProvisionDialogOpen(true);
            }}>
              <Plus className="w-4 h-4 mr-2" /> Назначить peer
            </Button>
          </div>
        </div>

          <details className="mb-5 rounded-xl border bg-muted/10 p-4"><summary className="cursor-pointer text-sm font-medium">Доступная телеметрия</summary>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <Activity className="h-4 w-4 text-primary" aria-hidden="true" /> Данные маршрутизатора
            </h2>
            <dl className="mt-4 space-y-3 text-xs">
              <div className="flex items-center justify-between gap-3 border-b border-border pb-2">
                <dt className="text-muted-foreground">Состояние пира</dt><dd className="font-mono text-success">Доступно</dd>
              </div>
              <div className="flex items-center justify-between gap-3 border-b border-border pb-2">
                <dt className="text-muted-foreground">Время handshake</dt><dd className="font-mono text-success">Доступно</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-muted-foreground">Счётчики трафика пира</dt><dd className="font-mono text-warning">Не предоставляются</dd>
              </div>
            </dl>
            <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
              Маршрутизатор не передаёт счётчики трафика, координаты шлюза и замеры задержки. Эти показатели здесь не отображаются.
            </p>
          </details>

        {/* VPN Nodes Grid */}
        <h2 className="mb-4 mt-6 text-base font-semibold">Назначения устройств</h2>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {isLoading && <div className="col-span-1 xl:col-span-2 text-center text-muted-foreground p-10">Загружаем назначения устройств…</div>}
          {peersError && <div className="col-span-1 xl:col-span-2 rounded border border-destructive/30 p-4 text-sm text-destructive" role="alert">Не удалось загрузить VPN peers. Состояние не обновлено; обновите страницу или повторите запрос позже.</div>}
          {!isLoading && !peersError && visibleTunnels.length === 0 && <div className="col-span-1 xl:col-span-2 rounded border border-dashed border-border p-8 text-center text-sm text-muted-foreground">{search ? 'По этому запросу устройств не найдено.' : 'Устройствам ещё не назначены адреса.'}</div>}
          {!isLoading && !peersError && visibleTunnels.map(tunnel => (
            <div key={tunnel.id} className="bg-card/60 border border-border rounded-2xl flex flex-col hover:border-primary/25 transition-colors relative overflow-hidden group">

              <div className="p-5 flex-1 relative z-10">
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="text-sm font-semibold text-foreground">{tunnel.name}</h3>
                      {tunnel.active && (
                        <Badge variant="outline" className="text-[11px] border-success/20 text-success bg-success/5">LIVE</Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground font-mono flex items-center gap-2">
                      <span className="font-bold text-primary/80">Peer {tunnel.id.slice(0, 8)}</span>
                      <span>•</span>
                      <span>{tunnel.endpoint ?? 'Адрес не сообщён'}</span>
                    </div>
                  </div>
                  <Badge variant="outline" className={`text-[10px] ${tunnel.active ? 'border-success text-success' : tunnel.status === 'ERROR' ? 'border-destructive text-destructive' : 'border-warning text-warning'}`}>
                    {tunnel.status}
                  </Badge>
                </div>

                <div className="grid grid-cols-1 gap-3 rounded border border-border/70 bg-background/40 p-3 sm:grid-cols-2">
                  <div className="min-w-0">
                    <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Устройство</div>
                    <button type="button" className="mt-1 truncate font-mono text-xs text-primary hover:underline" onClick={() => router.push(`/devices/${tunnel.deviceId}`)}>
                      {tunnel.deviceId}
                    </button>
                  </div>
                  <div className="min-w-0">
                    <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Последний handshake</div>
                    <time dateTime={tunnel.lastHandshakeAt ?? undefined} className="mt-1 block truncate font-mono text-xs text-foreground">
                      {formatHandshake(tunnel.lastHandshakeAt)}
                    </time>
                  </div>
                </div>
              </div>

              <div className="border-t border-border bg-background/50 p-3 px-5 flex flex-wrap items-center justify-between gap-3 relative z-10 mt-auto">
                <div className="text-xs text-muted-foreground flex items-center gap-2">
                  <Activity className={`w-3.5 h-3.5 ${tunnel.active ? 'text-success' : 'text-warning'}`} />
                  {tunnel.active ? 'Handshake менее 3 минут назад' : 'Нет свежего handshake'}
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-9 text-xs font-medium text-muted-foreground hover:text-foreground"
                    onClick={() => {
                      openOperation('reboot', [tunnel.deviceId]);
                    }}
                    disabled={!canReboot || !fresh || unresolved.has(tunnel.deviceId)}
                  >
                    <RotateCcw className="w-3 h-3 mr-1" /> Перезагрузка
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-9 text-xs font-medium text-muted-foreground hover:text-foreground"
                    onClick={() => {
                      router.push(`/logs?device_id=${encodeURIComponent(tunnel.deviceId)}`);
                    }}
                  >
                    <FileText className="w-3 h-3 mr-1" /> Логи
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-9 text-xs font-medium text-primary hover:text-primary hover:bg-primary/10"
                    onClick={() => setConfigureDialogOpen(tunnel.id)}
                  >
                    <Wrench className="w-3 h-3 mr-1" /> Параметры
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Диалог Политики — статистика пула и killswitch */}
      <Dialog open={policyDialogOpen} onOpenChange={setPolicyDialogOpen}>
        <DialogContent layout="workspace">
          <DialogHeader>
            <DialogTitle>Политики инфраструктуры</DialogTitle><DialogDescription>Адресный пул и операции с назначениями устройств. Настройки Android-сервиса проверяются отдельно.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            {poolStats && (
              <div className="grid grid-cols-2 gap-3 text-sm font-mono">
                <div className="bg-muted p-3 rounded border border-border">
                  <div className="text-[10px] text-muted-foreground uppercase">Всего адресов</div>
                  <div className="text-lg font-bold">{poolStats.total_ips}</div>
                </div>
                <div className="bg-muted p-3 rounded border border-border">
                  <div className="text-[10px] text-muted-foreground uppercase">Назначено</div>
                  <div className="text-lg font-bold text-primary">{poolStats.allocated}</div>
                </div>
                <div className="bg-muted p-3 rounded border border-border">
                  <div className="text-[10px] text-muted-foreground uppercase">Свободно</div>
                  <div className="text-lg font-bold text-success">{poolStats.free}</div>
                </div>
                <div className="bg-muted p-3 rounded border border-border">
                  <div className="text-[10px] text-muted-foreground uppercase">Handshake менее 3 минут назад</div>
                  <div className="text-lg font-bold">{activeTunnelCount}</div>
                </div>
              </div>
            )}
            <div className="flex gap-2">
              <Button
                variant="destructive"
                size="sm"
                className="flex-1"
                onClick={() => {
                  const deviceIds = rawPeers.flatMap((peer) => peer.status === 'assigned' && peer.device_id ? [peer.device_id] : []);
                  openOperation('enable', deviceIds);
                }}
                disabled={!canVpn || !fresh || !rawPeers.some(p => p.status === 'assigned' && p.device_id) || unresolved.size > 0}
              >
                <Lock className="w-3 h-3 mr-1" /> Kill Switch ON (ALL)
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                onClick={() => {
                  const deviceIds = rawPeers.flatMap((peer) => peer.status === 'assigned' && peer.device_id ? [peer.device_id] : []);
                  openOperation('disable', deviceIds);
                }}
                disabled={!canVpn || !fresh || !rawPeers.some(p => p.status === 'assigned' && p.device_id) || unresolved.size > 0}
              >
                Kill Switch OFF
              </Button>
            </div>
          </DialogBody>
        </DialogContent>
      </Dialog>

      {/* Диалог Назначить peer — назначить VPN устройству */}
      <Dialog open={provisionDialogOpen && provisionScope === scope} onOpenChange={(open) => {
        if (provisionBusy.current) return;
        setProvisionDialogOpen(open);
        if (!open) {
          setProvisionDeviceId('');
          setProvisionError(null);
        }
      }}>
        <DialogContent layout="workspace">
          <DialogHeader>
            <DialogTitle>Назначение адреса из пула</DialogTitle><DialogDescription>Выбери устройство. Назначение router peer не подтверждает подключение VPN на Android.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <div className="space-y-1">
              <Label className="text-xs font-mono">Устройство</Label>
              <DeviceSearchSelect
                value={provisionDeviceId}
                onChange={(deviceId) => {
                  setProvisionDeviceId(deviceId);
                  setProvisionError(null);
                }}
                disabled={assignVpn.isPending || provisionDone}
                excludedIds={peerDeviceIds}
                placeholder="Выбери устройство…"
              />
            </div>
            {provisionNotice && <p role="status" className="rounded-lg border p-3 text-sm">{provisionNotice}</p>}
            {provisionError && <p className="text-sm text-destructive" role="alert">{provisionError}</p>}
            <Button
              className="w-full"
              disabled={!canVpn || !fresh || provisionDone || !provisionDeviceId || peerDeviceIds.has(provisionDeviceId) || assignVpn.isPending}
              onClick={async () => {
                if (provisionBusy.current || provisionDone || !canVpn || !fresh || scope !== vpnActorScope() || !provisionDeviceId || peerDeviceIds.has(provisionDeviceId)) return;
                provisionBusy.current = true; setProvisionError(null);
                try {
                  const response = await assignVpn.mutateAsync({ device_id: provisionDeviceId });
                  if (scope !== vpnActorScope()) return;
                  const data = response.data;
                  if (!data || data.device_id !== provisionDeviceId || typeof data.peer_id !== 'string' || !data.peer_id || typeof data.assigned_ip !== 'string' || !data.assigned_ip) throw new Error('Invalid assignment receipt');
                  setProvisionDone(true);
                  setProvisionNotice(`Router assignment: ${data.peer_id}, ${data.assigned_ip}. Применение конфигурации APK и handshake ещё не подтверждены.`);
                } catch (error) {
                  if (scope !== vpnActorScope()) return;
                  const failure = controlFailure(error);
                  setProvisionDone(true);
                  setProvisionError(failure.message);
                  if (failure.unknown) setOutcomes(prev => ({ scope, rows: [...(prev.scope === scope ? prev.rows.filter(v => v.deviceId !== provisionDeviceId) : []), { deviceId: provisionDeviceId, outcome: 'unknown', detail: failure.message, retryable: false }] }));
                } finally { provisionBusy.current = false; }
              }}
            >
              {assignVpn.isPending ? 'Назначаем…' : 'Назначить адрес'}
            </Button>
          </DialogBody>
        </DialogContent>
      </Dialog>

      {/* Диалог Configure — ротация IP и killswitch для конкретного пира */}
      <Dialog open={!!configureDialogOpen} onOpenChange={(open) => { if (!open) setConfigureDialogOpen(null); }}>
        <DialogContent layout="workspace">
          <DialogHeader>
            <DialogTitle>Параметры назначения</DialogTitle><DialogDescription>Состояние назначения и сетевые операции выбранного устройства.</DialogDescription>
          </DialogHeader>
          {configureDialogOpen && (() => {
            const peer = rawPeers.find((p) => p.id === configureDialogOpen);
            if (!peer) return <p className="text-sm text-muted-foreground">Назначение не найдено</p>;
            return (
              <DialogBody className="space-y-4">
                <div className="break-words rounded-xl border bg-muted/15 p-4 text-sm font-mono space-y-2 [overflow-wrap:anywhere]">
                  <p><span className="text-muted-foreground">IP:</span> {peer.assigned_ip ?? '—'}</p>
                  <p><span className="text-muted-foreground">Устройство:</span> {peer.device_id ?? 'Не привязано'}</p>
                  <p><span className="text-muted-foreground">Состояние:</span> {peer.status}</p>
                  <p><span className="text-muted-foreground">Handshake:</span> {peer.is_active ? 'Менее 3 минут назад' : 'Нет свежего handshake'}</p>
                  <p><span className="text-muted-foreground">Последний handshake:</span> {formatHandshake(peer.last_handshake_at)}</p>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => {
                      if (!peer.device_id || peer.status !== 'assigned') return;
                      openOperation('rotate', [peer.device_id]);
                    }}
                    disabled={!canVpn || !fresh || !peer.device_id || peer.status !== 'assigned' || unresolved.has(peer.device_id)}
                  >
                    <RotateCcw className="w-3 h-3 mr-1" /> Сменить адрес
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    className="flex-1"
                    onClick={() => {
                      if (!peer.device_id || peer.status !== 'assigned') return;
                      openOperation('enable', [peer.device_id]);
                    }}
                    disabled={!canVpn || !fresh || !peer.device_id || peer.status !== 'assigned' || unresolved.has(peer.device_id)}
                  >
                    <Lock className="w-3 h-3 mr-1" /> Kill Switch
                  </Button>
                </div>
              </DialogBody>
            );
          })()}
        </DialogContent>
      </Dialog>
      {operation?.scope === scope && <VpnControlDialog key={`${scope}:${operation.kind}:${operation.ids.join(',')}`} {...operation} fresh={fresh} reload={async () => !(await query.refetch()).isError} onClose={() => setOperation(null)} onOutcomes={rows => setOutcomes(prev => ({ scope, rows: [...(prev.scope === scope ? prev.rows.filter(v => !rows.some(r => r.deviceId === v.deviceId)) : []), ...rows] }))} />}
    </div>
  );
}
