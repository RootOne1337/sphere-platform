'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useAuthStore } from '@/lib/store';
import { CreateReleaseDialog } from '@/src/features/updates/CreateReleaseDialog';
import { RecoveryDialog } from '@/src/features/updates/RecoveryDialog';
import { isManagedAndroidRelease } from '@/src/features/updates/recovery';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Release {
  id: string;
  platform: string;
  flavor: string;
  version_code: number;
  version_name: string;
  download_url: string;
  sha256: string;
  mandatory: boolean;
  changelog: string | null;
  created_at: string;
}

interface ReleasesResponse {
  releases: Release[];
  total: number;
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

function useReleases(platform?: string, flavor?: string, scope?: string) {
  return useQuery<ReleasesResponse>({
    queryKey: ['ota-releases', scope, platform ?? 'all', flavor ?? 'all'],
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams();
      if (platform) params.set('platform', platform);
      if (flavor) params.set('flavor', flavor);
      const { data } = await api.get<ReleasesResponse>(`/updates/?${params}`, { signal });
      if (!Array.isArray(data?.releases) || !Number.isInteger(data.total) || data.total < 0) {
        throw new Error('Invalid release catalog response');
      }
      return data;
    },
    // Reconcile catalog changes while the operator watches; never replay writes.
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function UpdatesPage() {
  const actor = useAuthStore(state => state.user);
  const sessionVersion = useAuthStore(state => state.sessionVersion);
  const scope = `${actor?.id}:${actor?.org_id}:${actor?.role}:${sessionVersion}`;
  return <UpdatesCatalog key={scope} scope={scope} canManage={actor?.role === 'super_admin'} canReadRecovery={Boolean(actor)} />;
}

function UpdatesCatalog({ scope, canManage, canReadRecovery }: { scope: string; canManage: boolean; canReadRecovery: boolean }) {
  const [platformFilter, setPlatformFilter] = useState<string>('all');
  const [flavorFilter, setFlavorFilter] = useState<string>('all');
  const { data, isPending, isFetching, isError, error, refetch } = useReleases(
    platformFilter === 'all' ? undefined : platformFilter,
    flavorFilter === 'all' ? undefined : flavorFilter,
    scope,
  );
  const [recoveryRelease, setRecoveryRelease] = useState<Release | null>(null);

  const releases = isError ? [] : data?.releases ?? [];

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this release?')) return;
    try {
      await api.delete(`/updates/${id}`);
      refetch();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Failed to delete');
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">OTA Updates</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Manage the releases offered by agents&apos; scheduled update checks
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" disabled={isFetching} onClick={() => { void refetch(); }}>
            Обновить релизы
          </Button>
          {canManage && <CreateReleaseDialog available={!isPending && !isFetching && !isError} onCreated={() => { void refetch(); }} />}
        </div>
      </div>

      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-muted-foreground">
        Publishing a release makes it eligible for all agents of that flavor on their next
        scheduled check <strong>only when the platform also matches</strong>. Registering a
        release does not upload the APK. Android scheduling and connectivity can delay
        delivery. Addressed OTA below uses a separate bounded permission and verifies
        its terminal receipt and installed version before expanding a rollout.
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <Select value={platformFilter} onValueChange={setPlatformFilter}>
          <SelectTrigger className="w-[180px]" aria-label="Platform filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All platforms</SelectItem>
            <SelectItem value="android">Android</SelectItem>
            <SelectItem value="android-canary">Android canary</SelectItem>
            <SelectItem value="pc">PC</SelectItem>
          </SelectContent>
        </Select>
        <Select value={flavorFilter} onValueChange={setFlavorFilter}>
          <SelectTrigger className="w-[160px]" aria-label="Flavor filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All flavors</SelectItem>
            <SelectItem value="enterprise">enterprise</SelectItem>
            <SelectItem value="dev">dev</SelectItem>
          </SelectContent>
        </Select>
        <Badge variant="outline">
          {isError || isPending ? 'Количество релизов неизвестно' : `${data?.total ?? 0} release${data?.total !== 1 ? 's' : ''}`}
        </Badge>
      </div>

      {/* Content */}
      {isPending && !isError && <div role="status" className="text-muted-foreground">Loading releases…</div>}
      {isError && (
        <div role="alert" className="rounded-lg border border-destructive/30 p-4">
          <p className="text-destructive">Не удалось загрузить релизы. Актуальный каталог неизвестен.</p>
          <p className="mt-1 text-sm text-muted-foreground">{getApiErrorMessage(error, 'Проверьте подключение и права доступа, затем повторите запрос.')}</p>
          <Button variant="outline" className="mt-3" disabled={isFetching} onClick={() => { void refetch(); }}>
            Повторить загрузку релизов
          </Button>
        </div>
      )}
      {!isPending && !isError && releases.length === 0 && (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground">
          No releases yet. Create one with &ldquo;+ New Release&rdquo;.
        </div>
      )}

      <div className="grid gap-4">
        {releases.map((release) => (
          <div key={release.id} className="rounded-lg border p-4 flex flex-col gap-3">
            {/* Release header */}
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-base">v{release.version_name}</span>
                  <Badge variant="outline" className="text-xs">{release.flavor}</Badge>
                  <Badge variant="outline" className="text-xs">{release.platform}</Badge>
                  {release.mandatory && (
                    <Badge variant="destructive" className="text-xs">Mandatory</Badge>
                  )}
                </div>
                {release.platform === 'android-canary' && (
                  <div className="text-xs text-amber-500 mt-1">
                    Canary catalog only: normal Android agents do not poll this channel.
                  </div>
                )}
                <div className="text-xs text-muted-foreground mt-1">
                  Version code {release.version_code} · Released {new Date(release.created_at).toLocaleString()}
                </div>
                {release.changelog && (
                  <div className="text-sm mt-1 text-muted-foreground">{release.changelog}</div>
                )}
                <div className="text-xs text-muted-foreground mt-1 font-mono truncate max-w-[400px]">
                  SHA-256: {release.sha256 || '—'}
                </div>
              </div>
              <div className="flex flex-wrap justify-end gap-2">
              {canReadRecovery && isManagedAndroidRelease(release) && <Button variant="outline" size="sm" disabled={isFetching || isError} onClick={() => setRecoveryRelease({ ...release })}>{canManage ? 'Адресное OTA' : 'Состояние OTA'}</Button>}
              {canManage && <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive shrink-0"
                disabled={isFetching}
                onClick={() => handleDelete(release.id)}
              >
                Delete
              </Button>}
              </div>
            </div>

          </div>
        ))}
      </div>
      {recoveryRelease && <RecoveryDialog release={recoveryRelease} scope={scope} canManage={canManage}
        available={!isError && !isFetching && Boolean(releases.find(value => value.id === recoveryRelease.id && value.sha256 === recoveryRelease.sha256 && value.version_code === recoveryRelease.version_code && value.version_name === recoveryRelease.version_name && value.download_url === recoveryRelease.download_url && value.flavor === recoveryRelease.flavor && value.platform === recoveryRelease.platform))}
        onClose={() => setRecoveryRelease(null)} />}
    </div>
  );
}
