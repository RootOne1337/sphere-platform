'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { usePoolStats, useVpnHealth } from '@/lib/hooks/useVpn';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import {
  Smartphone,
  Wifi,
  WifiOff,
  Activity,
  ShieldCheck,
  ShieldAlert,
  Server,
  Cpu,
  HardDrive,
  Zap,
} from 'lucide-react';

/* ── Device fleet summary ── */
interface FleetStats {
  total: number;
  online: number;
  offline: number;
  busy: number;
  vpn_active: number;
}

function useFleetStats() {
  return useQuery<FleetStats>({
    queryKey: ['dashboard', 'fleet'],
    queryFn: async () => {
      // Fetch all devices (lightweight)
      const { data } = await api.get('/devices', {
        params: { per_page: 1 },
      });
      const total = data.total ?? 0;

      // Fetch per-status counts in parallel
      const [onlineRes, offlineRes] = await Promise.all([
        api.get('/devices', { params: { status: 'online', per_page: 1 } }),
        api.get('/devices', { params: { status: 'offline', per_page: 1 } }),
      ]);
      const online = onlineRes.data.total ?? 0;
      const offline = offlineRes.data.total ?? 0;

      return {
        total,
        online,
        offline,
        busy: Math.max(0, total - online - offline),
        vpn_active: 0,
      };
    },
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}

/* ── Stat card ── */
function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  color = 'text-primary',
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ElementType;
  color?: string;
}) {
  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            <p className="text-3xl font-bold mt-1">{value}</p>
            {subtitle && (
              <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
            )}
          </div>
          <Icon className={`w-8 h-8 ${color} opacity-60`} />
        </div>
      </CardContent>
    </Card>
  );
}

/* ── Device status distribution ── */
function DeviceDistribution({ stats }: { stats: FleetStats }) {
  const pctOnline = stats.total > 0 ? (stats.online / stats.total) * 100 : 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Device Fleet</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-3">
          <Badge variant="default" className="bg-green-600">
            Online
          </Badge>
          <Progress value={pctOnline} className="flex-1" />
          <span className="text-sm font-mono w-12 text-right">
            {stats.online}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant="secondary">Offline</Badge>
          <Progress
            value={
              stats.total > 0 ? (stats.offline / stats.total) * 100 : 0
            }
            className="flex-1"
          />
          <span className="text-sm font-mono w-12 text-right">
            {stats.offline}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant="outline">Busy</Badge>
          <Progress
            value={stats.total > 0 ? (stats.busy / stats.total) * 100 : 0}
            className="flex-1"
          />
          <span className="text-sm font-mono w-12 text-right">
            {stats.busy}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

/* ── VPN stats card ── */
function VpnOverview() {
  const { data: pool } = usePoolStats();
  const { data: health } = useVpnHealth();
  const utilization =
    pool && pool.total_capacity > 0
      ? Math.round(((pool.used ?? 0) / pool.total_capacity) * 100)
      : 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">VPN Network</CardTitle>
          {health?.status === 'ok' ? (
            <Badge variant="default" className="bg-green-600 gap-1">
              <ShieldCheck className="w-3 h-3" />
              Healthy
            </Badge>
          ) : (
            <Badge variant="destructive" className="gap-1">
              <ShieldAlert className="w-3 h-3" />
              {health?.status ?? 'Unknown'}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-muted-foreground">Active Tunnels</p>
            <p className="text-xl font-bold">{pool?.active_tunnels ?? 0}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Pool Usage</p>
            <p className="text-xl font-bold">{utilization}%</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Free IPs</p>
            <p className="text-xl font-bold">{pool?.free ?? 0}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Stale Tunnels</p>
            <p className="text-xl font-bold text-amber-500">
              {pool?.stale_tunnels ?? 0}
            </p>
          </div>
        </div>
        <Progress value={utilization} />
      </CardContent>
    </Card>
  );
}

/* ── System health card ── */
function SystemHealth() {
  const { data } = useQuery({
    queryKey: ['dashboard', 'health'],
    queryFn: async () => {
      const { data } = await api.get('/health');
      return data as { status: string; version: string };
    },
    refetchInterval: 60_000,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">System</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-3">
          <Server className="w-4 h-4 text-muted-foreground" />
          <span className="text-sm">Backend</span>
          <Badge
            variant="default"
            className={
              data?.status === 'ok'
                ? 'bg-green-600 ml-auto'
                : 'bg-red-600 ml-auto'
            }
          >
            {data?.status ?? 'checking...'}
          </Badge>
        </div>
        <div className="flex items-center gap-3">
          <Zap className="w-4 h-4 text-muted-foreground" />
          <span className="text-sm">Version</span>
          <span className="text-sm font-mono ml-auto text-muted-foreground">
            {data?.version ?? '—'}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

/* ── Dashboard page ── */
export default function DashboardPage() {
  const { data: fleet, isLoading } = useFleetStats();

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Platform overview and analytics
        </p>
      </div>

      {/* Top stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Devices"
          value={fleet?.total ?? '—'}
          icon={Smartphone}
          color="text-blue-500"
        />
        <StatCard
          title="Online"
          value={fleet?.online ?? '—'}
          subtitle={
            fleet && fleet.total > 0
              ? `${Math.round((fleet.online / fleet.total) * 100)}% of fleet`
              : undefined
          }
          icon={Wifi}
          color="text-green-500"
        />
        <StatCard
          title="Offline"
          value={fleet?.offline ?? '—'}
          icon={WifiOff}
          color="text-red-400"
        />
        <StatCard
          title="Active Tasks"
          value={fleet?.busy ?? '—'}
          icon={Activity}
          color="text-amber-500"
        />
      </div>

      {/* Detail sections */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <DeviceDistribution stats={fleet ?? { total: 0, online: 0, offline: 0, busy: 0, vpn_active: 0 }} />
        <VpnOverview />
        <SystemHealth />
      </div>
    </div>
  );
}
