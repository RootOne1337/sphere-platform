'use client';
import { use, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import Link from 'next/link';
import { Monitor, Wifi, Zap } from 'lucide-react';

interface Props {
  params: Promise<{ id: string }>;
}

interface DeviceDetail {
  id: string;
  name: string;
  android_id: string;
  model: string;
  android_version: string;
  tags: string[];
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

export default function DeviceDetailPage({ params }: Props) {
  const { id } = use(params);
  const qc = useQueryClient();

  const { data: device, isLoading } = useQuery<DeviceDetail>({
    queryKey: ['devices', id],
    queryFn: async () => {
      const { data } = await api.get(`/devices/${id}`);
      return data;
    },
  });

  const connectAdb = useMutation({
    mutationFn: () => api.post(`/devices/${id}/connect`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices', id] }),
  });

  const deleteDevice = useMutation({
    mutationFn: () => api.delete(`/devices/${id}`),
  });

  if (isLoading) return <div className="p-6 text-muted-foreground">Loading…</div>;
  if (!device) return <div className="p-6 text-muted-foreground">Device not found</div>;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{device.name}</h1>
          <p className="text-sm text-muted-foreground font-mono">{device.id}</p>
        </div>
        <div className="flex gap-2">
          <Button asChild variant="outline">
            <Link href={`/stream/${device.id}`}>
              <Monitor className="w-4 h-4 mr-2" /> Stream
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/devices">Back</Link>
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader><CardTitle className="text-sm">Device Info</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Row label="Model" value={device.model} />
            <Row label="Android" value={device.android_version} />
            <Row label="Android ID" value={device.android_id} />
            <Row label="Group" value={device.group_name ?? '—'} />
            <Row label="Created" value={new Date(device.created_at).toLocaleString()} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-sm">Status</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${device.status === 'online' ? 'bg-green-500' : device.status === 'busy' ? 'bg-yellow-500' : 'bg-gray-500'}`} />
              <span className="capitalize">{device.status}</span>
            </div>
            <Row label="Battery" value={device.battery_level != null ? `${device.battery_level}%` : '—'} />
            <Row label="Last Seen" value={device.last_seen ? new Date(device.last_seen).toLocaleString() : '—'} />
            <div className="flex gap-2">
              <Badge variant={device.adb_connected ? 'default' : 'outline'}>
                ADB {device.adb_connected ? 'Connected' : 'Disconnected'}
              </Badge>
              <Badge variant={device.vpn_assigned ? 'default' : 'outline'}>
                <Wifi className="w-3 h-3 mr-1" />
                VPN {device.vpn_assigned ? 'On' : 'Off'}
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-sm">Actions</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <Button
              className="w-full"
              variant="outline"
              onClick={() => connectAdb.mutate()}
              disabled={connectAdb.isPending}
            >
              <Zap className="w-4 h-4 mr-2" />
              {connectAdb.isPending ? 'Connecting…' : 'ADB Connect'}
            </Button>
            <Button
              className="w-full"
              variant="destructive"
              onClick={() => {
                if (confirm('Delete this device?')) deleteDevice.mutate();
              }}
              disabled={deleteDevice.isPending}
            >
              Delete Device
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Tags */}
      {device.tags.length > 0 && (
        <div>
          <h3 className="text-sm font-medium mb-2">Tags</h3>
          <div className="flex gap-1 flex-wrap">
            {device.tags.map((tag) => (
              <Badge key={tag} variant="outline">{tag}</Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium truncate ml-2">{value}</span>
    </div>
  );
}
