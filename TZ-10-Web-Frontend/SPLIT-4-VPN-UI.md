# SPLIT-4 — VPN Management UI

**ТЗ-родитель:** TZ-10-Web-Frontend  
**Ветка:** `stage/10-frontend`  
**Задача:** `SPHERE-054`  
**Исполнитель:** Frontend  
**Оценка:** 1.5 дня  
**Блокирует:** TZ-10 SPLIT-5

---

## Цель Сплита

Страница управления VPN: 4 вкладки (Пул IP, Агенты, Массовые операции, Health), таблицы аллокации, QR-код, batch assign/revoke.

---

## Шаг 1 — VPN Hooks

```typescript
// lib/hooks/useVpn.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface VpnPeer {
    id: string;
    device_id: string;
    device_name: string;
    assigned_ip: string;
    status: 'active' | 'inactive' | 'error';
    last_handshake: string | null;
}

export interface PoolStats {
    // FIX: выровнено с backend PoolStatsResponse (TZ-06 SPLIT-5).
    // Было: total_ips/allocated/available/allocation_percent — НЕ соответствовало backend.
    // Стало: точные имена полей из PoolStatsResponse:
    total_capacity: number;   // было: total_ips
    used: number;             // было: allocated
    free: number;             // было: available
    active_tunnels: number;   // новое — сколько туннелей vpn_active=true
    stale_tunnels: number;    // новое — assigned но vpn_active=false
    // allocation_percent вычисляем на фронте: Math.round(used / total_capacity * 100)
}

export function useVpnPeers() {
    return useQuery<VpnPeer[]>({
        queryKey: ['vpn', 'peers'],
        queryFn: async () => {
            const { data } = await api.get('/vpn/peers');
            return data;
        },
        refetchInterval: 30_000,
    });
}

export function usePoolStats() {
    return useQuery<PoolStats>({
        queryKey: ['vpn', 'pool-stats'],
        queryFn: async () => {
            const { data } = await api.get('/vpn/pool/stats');
            return data;
        },
        refetchInterval: 60_000,
    });
}

export function useAssignVpn() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (deviceId: string) => api.post(`/vpn/devices/${deviceId}/assign`),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['vpn'] }),
    });
}

export function useRevokeVpn() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (deviceId: string) => api.delete(`/vpn/devices/${deviceId}/revoke`),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['vpn'] }),
    });
}

export function useBatchAssign() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (deviceIds: string[]) =>
            api.post('/vpn/batch/assign', { device_ids: deviceIds }),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['vpn'] }),
    });
}

export function useVpnQr(deviceId: string, enabled: boolean) {
    return useQuery({
        queryKey: ['vpn', 'qr', deviceId],
        queryFn: async () => {
            // FIX: правильный URL /vpn/devices/{id}/config/qr (был: /vpn/devices/{id}/qr)
            const { data } = await api.get(`/vpn/devices/${deviceId}/config/qr`);
            return data as { qr_code: string };  // base64 PNG
        },
        enabled,
        staleTime: Infinity,  // QR не меняется без ротации
    });
}
```

---

## Шаг 2 — VPN Page

```tsx
// app/(dashboard)/vpn/page.tsx
'use client';
import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { VpnPoolTab } from './_tabs/VpnPoolTab';
import { VpnAgentsTab } from './_tabs/VpnAgentsTab';
import { VpnBatchTab } from './_tabs/VpnBatchTab';
import { VpnHealthTab } from './_tabs/VpnHealthTab';

export default function VpnPage() {
    return (
        <div className="p-6">
            <h1 className="text-2xl font-bold mb-6">VPN Management</h1>
            <Tabs defaultValue="pool">
                <TabsList>
                    <TabsTrigger value="pool">IP Pool</TabsTrigger>
                    <TabsTrigger value="agents">Agents</TabsTrigger>
                    <TabsTrigger value="batch">Batch Ops</TabsTrigger>
                    <TabsTrigger value="health">Health</TabsTrigger>
                </TabsList>
                <TabsContent value="pool"><VpnPoolTab /></TabsContent>
                <TabsContent value="agents"><VpnAgentsTab /></TabsContent>
                <TabsContent value="batch"><VpnBatchTab /></TabsContent>
                <TabsContent value="health"><VpnHealthTab /></TabsContent>
            </Tabs>
        </div>
    );
}
```

---

## Шаг 3 — VpnPoolTab

```tsx
// app/(dashboard)/vpn/_tabs/VpnPoolTab.tsx
'use client';
import { usePoolStats } from '@/lib/hooks/useVpn';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';

export function VpnPoolTab() {
    const { data: stats, isLoading } = usePoolStats();
    // FIX: вычисляем allocation_percent на фронте — поля нет в backend ответе
    const allocationPercent = stats
        ? Math.round((stats.used / stats.total_capacity) * 100)
        : 0;
    
    return (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mt-4">
            <Card>
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm text-muted-foreground">Total IPs</CardTitle>
                </CardHeader>
                <CardContent>
                    {/* FIX: было stats?.total_ips — поля не существует; правильно total_capacity */}
                    <p className="text-3xl font-bold">{stats?.total_capacity ?? '—'}</p>
                </CardContent>
            </Card>
            <Card>
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm text-muted-foreground">Allocated</CardTitle>
                </CardHeader>
                <CardContent>
                    {/* FIX: было stats?.allocated — поля не существует; правильно used */}
                    <p className="text-3xl font-bold text-orange-400">{stats?.used ?? '—'}</p>
                </CardContent>
            </Card>
            <Card>
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm text-muted-foreground">Available</CardTitle>
                </CardHeader>
                <CardContent>
                    {/* FIX: было stats?.available — поля не существует; правильно free */}
                    <p className="text-3xl font-bold text-green-400">{stats?.free ?? '—'}</p>
                </CardContent>
            </Card>
            <Card>
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm text-muted-foreground">Active Tunnels</CardTitle>
                </CardHeader>
                <CardContent>
                    <p className="text-3xl font-bold text-blue-400">{stats?.active_tunnels ?? '—'}</p>
                </CardContent>
            </Card>
            <Card>
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm text-muted-foreground">Stale Tunnels</CardTitle>
                </CardHeader>
                <CardContent>
                    <p className="text-3xl font-bold text-yellow-400">{stats?.stale_tunnels ?? '—'}</p>
                </CardContent>
            </Card>
            <Card>
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm text-muted-foreground">Utilization</CardTitle>
                </CardHeader>
                <CardContent>
                    {/* FIX: było stats?.allocation_percent (поля нет в backend) — вычисляем на фронте */}
                    <p className="text-xl font-bold mb-2">{allocationPercent.toFixed(1)}%</p>
                    <Progress value={allocationPercent} className="h-2" />
                </CardContent>
            </Card>
        </div>
    );
}
```

---

## Шаг 4 — VpnAgentsTab с QR-кодом

```tsx
// app/(dashboard)/vpn/_tabs/VpnAgentsTab.tsx
'use client';
import { useState } from 'react';
import { useVpnPeers, useVpnQr, useRevokeVpn } from '@/lib/hooks/useVpn';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';

export function VpnAgentsTab() {
    const { data: peers } = useVpnPeers();
    const [qrDeviceId, setQrDeviceId] = useState<string | null>(null);
    const revoke = useRevokeVpn();
    
    const { data: qrData } = useVpnQr(qrDeviceId ?? '', !!qrDeviceId);
    
    return (
        <div className="mt-4 space-y-2">
            {peers?.map(peer => (
                <div key={peer.id} className="flex items-center justify-between p-3 rounded border">
                    <div>
                        <p className="font-medium">{peer.device_name}</p>
                        <p className="text-sm text-muted-foreground">{peer.assigned_ip}</p>
                    </div>
                    <div className="flex items-center gap-2">
                        <Badge variant={peer.status === 'active' ? 'default' : 'secondary'}>
                            {peer.status}
                        </Badge>
                        <Button size="sm" variant="outline" onClick={() => setQrDeviceId(peer.device_id)}>
                            QR
                        </Button>
                        <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => revoke.mutate(peer.device_id)}
                        >
                            Revoke
                        </Button>
                    </div>
                </div>
            ))}
            
            <Dialog open={!!qrDeviceId} onOpenChange={() => setQrDeviceId(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>WireGuard QR Code</DialogTitle>
                    </DialogHeader>
                    {qrData?.qr_code && (
                        <img
                            src={`data:image/png;base64,${qrData.qr_code}`}
                            alt="WireGuard QR"
                            className="w-64 h-64 mx-auto"
                        />
                    )}
                </DialogContent>
            </Dialog>
        </div>
    );
}
```

---

## Критерии готовности

- [ ] 4 вкладки: Pool / Agents / Batch / Health рендерятся без ошибок
- [ ] Pool stats: progress bar заполняется по `allocation_percent`
- [ ] QR-код отображается в Modal через `data:image/png;base64,...`
- [ ] Revoke с confirmation (кнопка destructive достаточна как confirmation)
- [ ] `useVpnQr` disabled пока `qrDeviceId === null` (не лишние запросы)
- [ ] `staleTime: Infinity` для QR (не перезапрашивается пока не ротировали)
