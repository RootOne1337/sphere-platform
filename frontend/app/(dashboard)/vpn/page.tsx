'use client';

import { useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Network, Activity, Settings, Plus, Lock, Globe, RotateCcw, FileText, Wrench, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import { VPNMap } from '@/src/features/vpn/VPNMap';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { DeviceSearchSelect } from '@/components/sphere/DeviceSearchSelect';

import { useVpnPeers, usePoolStats, useAssignVpn, useVpnRotate, useVpnKillSwitch } from '@/lib/hooks/useVpn';
import { useBulkAction } from '@/lib/hooks/useDevices';
import { getApiErrorMessage } from '@/lib/apiError';

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
  if (!value) return 'No handshake reported';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'Invalid timestamp' : `${date.toISOString().replace('T', ' ').slice(0, 19)} UTC`;
}

export default function VPNManagerPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');

  // Диалоги
  const [policyDialogOpen, setPolicyDialogOpen] = useState(false);
  const [provisionDialogOpen, setProvisionDialogOpen] = useState(false);
  const [configureDialogOpen, setConfigureDialogOpen] = useState<string | null>(null); // peer id
  const [provisionDeviceId, setProvisionDeviceId] = useState('');
  const [provisionError, setProvisionError] = useState<string | null>(null);

  // Используем хук вместо инлайн-запроса для единообразия и корректного кеширования
  const { data: rawPeers = [], isLoading, isError: peersError } = useVpnPeers();
  const { data: poolStats, isLoading: poolStatsLoading, isError: poolStatsError } = usePoolStats();
  const assignVpn = useAssignVpn();
  const rotateVpn = useVpnRotate();
  const killSwitch = useVpnKillSwitch();
  const bulkAction = useBulkAction();

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
    <div className="flex flex-col h-full bg-card">
      {/* Header Area */}
      <div className="px-6 py-5 border-b border-border bg-muted shrink-0">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Network className="w-5 h-5 text-primary" />
              <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">VPN Tunneling Manager</h1>
            </div>
            <p className="text-xs text-muted-foreground font-mono max-w-2xl">
              Управление VPN peer assignments и свежестью handshake. Трафик RX/TX пока не публикуется API.
            </p>
          </div>

          <div className="flex items-center gap-4 bg-black/40 p-3 rounded-sm border border-border">
            <div className="flex space-x-6">
              <div className="flex flex-col">
                <span className="text-[10px] text-muted-foreground uppercase tracking-widest font-bold flex items-center gap-1">
                  <Lock className="w-3 h-3" /> Assigned
                </span>
                <span className="text-sm text-foreground font-mono font-bold">{poolStatsLoading ? '…' : poolStatsError ? 'Unavailable' : poolStats?.allocated ?? '—'}</span>
              </div>
              <div className="flex flex-col border-l border-border pl-6">
                <span className="text-[10px] text-muted-foreground uppercase tracking-widest font-bold flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3" /> Recent handshake
                </span>
                <span className="text-sm text-success font-mono font-bold">{activeTunnelCount}</span>
              </div>
              <div className="flex flex-col border-l border-border pl-6">
                <span className="text-[10px] text-muted-foreground uppercase tracking-widest font-bold flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" /> No recent handshake
                </span>
                <span className="text-sm text-warning font-mono font-bold">{attentionTunnelCount}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="p-6 flex-1 overflow-auto">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Input
              placeholder="Search device ID, peer ID, or VPN IP…"
              className="w-72 h-9 bg-black/50 border-border font-mono text-xs focus-visible:ring-primary/50"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-3">
            <Button variant="outline" size="sm" className="h-9 border-border hover:bg-border" onClick={() => setPolicyDialogOpen(true)}>
              <Settings className="w-4 h-4 mr-2" /> Global Policy
            </Button>
            <Button variant="default" size="sm" className="h-9" onClick={() => {
              setProvisionDeviceId('');
              setProvisionError(null);
              setProvisionDialogOpen(true);
            }}>
              <Plus className="w-4 h-4 mr-2" /> Provision Node
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-6">
          <div className="xl:col-span-2">
            <VPNMap tunnels={visibleTunnels} />
          </div>
          <section className="rounded-sm border border-border bg-card p-4" aria-labelledby="vpn-telemetry-title">
            <h2 id="vpn-telemetry-title" className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <Activity className="h-4 w-4 text-primary" aria-hidden="true" /> Telemetry coverage
            </h2>
            <dl className="mt-4 space-y-3 text-xs">
              <div className="flex items-center justify-between gap-3 border-b border-border pb-2">
                <dt className="text-muted-foreground">Peer status</dt><dd className="font-mono text-success">Available</dd>
              </div>
              <div className="flex items-center justify-between gap-3 border-b border-border pb-2">
                <dt className="text-muted-foreground">Handshake timestamp</dt><dd className="font-mono text-success">Available</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-muted-foreground">Per-peer RX/TX bytes</dt><dd className="font-mono text-warning">Not exposed</dd>
              </div>
            </dl>
            <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
              Current `/vpn/peers` contract has no byte counters, gateway coordinates, or latency samples. No traffic graph is drawn from placeholder zeros.
            </p>
          </section>
        </div>

        {/* VPN Nodes Grid */}
        <h2 className="text-xs font-mono font-bold tracking-widest text-muted-foreground mb-3 uppercase mt-6 border-b border-border pb-2">Assigned VPN peers</h2>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {isLoading && <div className="col-span-1 xl:col-span-2 text-center text-muted-foreground p-10">Loading VPN peer state from API…</div>}
          {peersError && <div className="col-span-1 xl:col-span-2 rounded border border-destructive/30 p-4 text-sm text-destructive" role="alert">Не удалось загрузить VPN peers. Состояние не обновлено; обновите страницу или повторите запрос позже.</div>}
          {!isLoading && !peersError && visibleTunnels.length === 0 && <div className="col-span-1 xl:col-span-2 rounded border border-dashed border-border p-8 text-center text-sm text-muted-foreground">{search ? 'По этому запросу устройств не найдено.' : 'Назначенных VPN peers нет.'}</div>}
          {!isLoading && !peersError && visibleTunnels.map(tunnel => (
            <div key={tunnel.id} className="bg-muted border border-border rounded-sm flex flex-col hover:border-[#444] transition-colors relative overflow-hidden group">
              {/* Background Graphic */}
              <Globe className="absolute -right-8 -bottom-8 w-48 h-48 text-[#ffffff03] pointer-events-none group-hover:scale-110 transition-transform duration-700" strokeWidth={1} />

              <div className="p-5 flex-1 relative z-10">
                <div className="flex justify-between items-start mb-6">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="text-base font-bold font-mono text-foreground">{tunnel.name}</h3>
                      {tunnel.active && (
                        <Badge variant="outline" className="text-[9px] border-success text-success bg-success/5 animate-pulse">LIVE</Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground font-mono flex items-center gap-2">
                      <span className="font-bold text-primary/80">Peer {tunnel.id.slice(0, 8)}</span>
                      <span>•</span>
                      <span>{tunnel.endpoint ?? 'Address unavailable'}</span>
                    </div>
                  </div>
                  <Badge variant="outline" className={`text-[10px] ${tunnel.active ? 'border-success text-success' : tunnel.status === 'ERROR' ? 'border-destructive text-destructive' : 'border-warning text-warning'}`}>
                    {tunnel.status}
                  </Badge>
                </div>

                <div className="grid grid-cols-1 gap-3 rounded border border-border/70 bg-background/40 p-3 sm:grid-cols-2">
                  <div className="min-w-0">
                    <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Device ID</div>
                    <button type="button" className="mt-1 truncate font-mono text-xs text-primary hover:underline" onClick={() => router.push(`/devices/${tunnel.deviceId}`)}>
                      {tunnel.deviceId}
                    </button>
                  </div>
                  <div className="min-w-0">
                    <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Last handshake</div>
                    <time dateTime={tunnel.lastHandshakeAt ?? undefined} className="mt-1 block truncate font-mono text-xs text-foreground">
                      {formatHandshake(tunnel.lastHandshakeAt)}
                    </time>
                  </div>
                </div>
              </div>

              <div className="border-t border-border bg-[#151515] p-3 px-5 flex items-center justify-between relative z-10 mt-auto">
                <div className="text-[10px] uppercase tracking-widest font-bold text-muted-foreground flex items-center gap-2">
                  <Activity className={`w-3.5 h-3.5 ${tunnel.active ? 'text-success' : 'text-warning'}`} />
                  {tunnel.active ? 'Recent handshake (< 3 min)' : 'No recent handshake'}
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 text-[10px] uppercase font-bold tracking-widest text-muted-foreground hover:text-foreground"
                    onClick={() => {
                      bulkAction.mutate({ device_ids: [tunnel.deviceId], action: 'reboot' });
                    }}
                    disabled={bulkAction.isPending}
                  >
                    <RotateCcw className="w-3 h-3 mr-1" /> Reboot
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 text-[10px] uppercase font-bold tracking-widest text-muted-foreground hover:text-foreground"
                    onClick={() => {
                      router.push(`/logs?device_id=${encodeURIComponent(tunnel.deviceId)}`);
                    }}
                  >
                    <FileText className="w-3 h-3 mr-1" /> Logs
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-8 text-[10px] uppercase font-bold tracking-widest text-primary hover:text-primary hover:bg-primary/10"
                    onClick={() => setConfigureDialogOpen(tunnel.id)}
                  >
                    <Wrench className="w-3 h-3 mr-1" /> Configure
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Диалог Global Policy — статистика пула и killswitch */}
      <Dialog open={policyDialogOpen} onOpenChange={setPolicyDialogOpen}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle className="font-mono">Global VPN Policy</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            {poolStats && (
              <div className="grid grid-cols-2 gap-3 text-sm font-mono">
                <div className="bg-muted p-3 rounded border border-border">
                  <div className="text-[10px] text-muted-foreground uppercase">Total IPs</div>
                  <div className="text-lg font-bold">{poolStats.total_ips}</div>
                </div>
                <div className="bg-muted p-3 rounded border border-border">
                  <div className="text-[10px] text-muted-foreground uppercase">Allocated</div>
                  <div className="text-lg font-bold text-primary">{poolStats.allocated}</div>
                </div>
                <div className="bg-muted p-3 rounded border border-border">
                  <div className="text-[10px] text-muted-foreground uppercase">Free</div>
                  <div className="text-lg font-bold text-success">{poolStats.free}</div>
                </div>
                <div className="bg-muted p-3 rounded border border-border">
                  <div className="text-[10px] text-muted-foreground uppercase">Recent handshakes (&lt; 3 min)</div>
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
                  if (deviceIds.length > 0) killSwitch.mutate({ device_ids: deviceIds, enabled: true });
                }}
                disabled={killSwitch.isPending}
              >
                <Lock className="w-3 h-3 mr-1" /> Kill Switch ON (ALL)
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                onClick={() => {
                  const deviceIds = rawPeers.flatMap((peer) => peer.status === 'assigned' && peer.device_id ? [peer.device_id] : []);
                  if (deviceIds.length > 0) killSwitch.mutate({ device_ids: deviceIds, enabled: false });
                }}
                disabled={killSwitch.isPending}
              >
                Kill Switch OFF
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Диалог Provision Node — назначить VPN устройству */}
      <Dialog open={provisionDialogOpen} onOpenChange={(open) => {
        setProvisionDialogOpen(open);
        if (!open) {
          setProvisionDeviceId('');
          setProvisionError(null);
        }
      }}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle className="font-mono">Provision VPN Node</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-1">
              <Label className="text-xs font-mono">Устройство</Label>
              <DeviceSearchSelect
                value={provisionDeviceId}
                onChange={(deviceId) => {
                  setProvisionDeviceId(deviceId);
                  setProvisionError(null);
                }}
                disabled={assignVpn.isPending}
                excludedIds={peerDeviceIds}
                placeholder="Выбери устройство…"
              />
            </div>
            {provisionError && <p className="text-sm text-destructive" role="alert">{provisionError}</p>}
            <Button
              className="w-full"
              disabled={!provisionDeviceId || peerDeviceIds.has(provisionDeviceId) || assignVpn.isPending}
              onClick={async () => {
                if (!provisionDeviceId || peerDeviceIds.has(provisionDeviceId)) return;
                setProvisionError(null);
                try {
                  await assignVpn.mutateAsync({ device_id: provisionDeviceId });
                  setProvisionDeviceId('');
                  setProvisionDialogOpen(false);
                } catch (error) {
                  setProvisionError(getApiErrorMessage(error, 'Не удалось назначить VPN устройству. Проверьте состояние и повторите вручную.'));
                }
              }}
            >
              {assignVpn.isPending ? 'Provisioning…' : 'Assign VPN'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Диалог Configure — ротация IP и killswitch для конкретного пира */}
      <Dialog open={!!configureDialogOpen} onOpenChange={(open) => { if (!open) setConfigureDialogOpen(null); }}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle className="font-mono">Configure Tunnel</DialogTitle>
          </DialogHeader>
          {configureDialogOpen && (() => {
            const peer = rawPeers.find((p) => p.id === configureDialogOpen);
            if (!peer) return <p className="text-sm text-muted-foreground">Peer not found</p>;
            return (
              <div className="space-y-4 pt-2">
                <div className="text-sm font-mono space-y-1">
                  <p><span className="text-muted-foreground">IP:</span> {peer.assigned_ip ?? '—'}</p>
                  <p><span className="text-muted-foreground">Device ID:</span> {peer.device_id ?? 'No device linked'}</p>
                  <p><span className="text-muted-foreground">Status:</span> {peer.status}</p>
                  <p><span className="text-muted-foreground">Handshake:</span> {peer.is_active ? 'Recent (< 3 min)' : 'No recent handshake'}</p>
                  <p><span className="text-muted-foreground">Last handshake:</span> {formatHandshake(peer.last_handshake_at)}</p>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => {
                      if (!peer.device_id || peer.status !== 'assigned') return;
                      rotateVpn.mutate({ device_ids: [peer.device_id] });
                      setConfigureDialogOpen(null);
                    }}
                    disabled={rotateVpn.isPending || !peer.device_id || peer.status !== 'assigned'}
                  >
                    <RotateCcw className="w-3 h-3 mr-1" /> Rotate IP
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    className="flex-1"
                    onClick={() => {
                      if (!peer.device_id || peer.status !== 'assigned') return;
                      killSwitch.mutate({ device_ids: [peer.device_id], enabled: true });
                      setConfigureDialogOpen(null);
                    }}
                    disabled={killSwitch.isPending || !peer.device_id || peer.status !== 'assigned'}
                  >
                    <Lock className="w-3 h-3 mr-1" /> Kill Switch
                  </Button>
                </div>
              </div>
            );
          })()}
        </DialogContent>
      </Dialog>
    </div>
  );
}
