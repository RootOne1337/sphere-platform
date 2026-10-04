'use client';

import { Activity, CircleHelp, ShieldCheck, WifiOff } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

export interface VpnTopologyPeer {
  id: string;
  deviceId: string;
  endpoint: string | null;
  status: string;
  active: boolean;
  lastHandshakeAt: string | null;
}

function formatUtc(value: string | null): string {
  if (!value) return 'No handshake reported';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'Invalid timestamp' : `${date.toISOString().replace('T', ' ').slice(0, 19)} UTC`;
}

/** A truthful peer snapshot: the API has no geo coordinates or latency telemetry. */
export function VPNMap({ tunnels }: { tunnels: VpnTopologyPeer[] }) {
  const activeCount = tunnels.filter((peer) => peer.active).length;
  const nonActiveCount = tunnels.length - activeCount;

  return (
    <section className="rounded-sm border border-border bg-card p-4" aria-label="VPN peer snapshot">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Activity className="h-4 w-4 text-primary" aria-hidden="true" />
            Peer snapshot
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">Состояние из последнего ответа `/vpn/peers`</p>
        </div>
        <div className="flex gap-2 text-xs">
          <Badge variant="outline" className="border-success/50 text-success">Recent handshake · {activeCount}</Badge>
          <Badge variant="outline" className="border-border text-muted-foreground">No recent handshake · {nonActiveCount}</Badge>
        </div>
      </div>

      {tunnels.length === 0 ? (
        <div className="flex min-h-40 flex-col items-center justify-center gap-2 rounded border border-dashed border-border text-center">
          <CircleHelp className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm text-foreground">Нет VPN peers с привязанными устройствами</p>
          <p className="text-xs text-muted-foreground">Свободные адреса пула не считаются устройствами.</p>
        </div>
      ) : (
        <>
          <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {tunnels.slice(0, 6).map((peer) => (
              <li key={peer.id} className="min-w-0 rounded border border-border bg-muted/30 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-xs text-foreground">Device {peer.deviceId.slice(0, 8)}</span>
                  {peer.active
                    ? <ShieldCheck className="h-4 w-4 shrink-0 text-success" aria-label="Recent handshake" />
                    : <WifiOff className="h-4 w-4 shrink-0 text-muted-foreground" aria-label="No recent handshake" />}
                </div>
                <p className="mt-2 truncate font-mono text-xs text-primary">{peer.endpoint ?? 'Address unavailable'}</p>
                <div className="mt-2 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                  <span className="uppercase">{peer.status}</span>
                  <time dateTime={peer.lastHandshakeAt ?? undefined} className="truncate">{formatUtc(peer.lastHandshakeAt)}</time>
                </div>
              </li>
            ))}
          </ul>
          {tunnels.length > 6 && (
            <p className="mt-3 text-xs text-muted-foreground">Показаны 6 из {tunnels.length}; полный список ниже.</p>
          )}
        </>
      )}
    </section>
  );
}
