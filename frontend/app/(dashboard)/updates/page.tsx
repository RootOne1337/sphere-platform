'use client';
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
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
import { AgentDownloadPanel } from '@/src/features/updates/AgentDownloadPanel';

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
      if (!Array.isArray(data?.releases) || data.total !== data.releases.length
        || data.releases.some(release => !release || typeof release.id !== 'string' || !release.id)) {
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
  const canRead = Boolean(actor && ['viewer', 'script_runner', 'device_manager', 'org_admin', 'org_owner', 'super_admin'].includes(actor.role));
  return <UpdatesCatalog key={scope} scope={scope} canManage={actor?.role === 'super_admin'} canRead={canRead} />;
}

function UpdatesCatalog({ scope, canManage, canRead }: { scope: string; canManage: boolean; canRead: boolean }) {
  const [platformFilter, setPlatformFilter] = useState<string>('all');
  const [flavorFilter, setFlavorFilter] = useState<string>('all');
  const [deleteTarget, setDeleteTarget] = useState<Release | null>(null);
  const [deletePending, setDeletePending] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const [unconfirmedDeletes, setUnconfirmedDeletes] = useState<ReadonlySet<string>>(() => new Set());
  const [notice, setNotice] = useState('');
  const deleteRequest = useRef<AbortController | null>(null);
  const deleteTrigger = useRef<HTMLButtonElement | null>(null);
  const refreshButton = useRef<HTMLButtonElement | null>(null);
  useEffect(() => () => { deleteRequest.current?.abort(); }, []);
  const { data, isPending, isFetching, isError, error, refetch } = useReleases(
    platformFilter === 'all' ? undefined : platformFilter,
    flavorFilter === 'all' ? undefined : flavorFilter,
    scope,
  );
  const [recoveryRelease, setRecoveryRelease] = useState<Release | null>(null);

  const releases = isError ? [] : data?.releases ?? [];
  const filtered = platformFilter !== 'all' || flavorFilter !== 'all';
  const deleteUnknown = Boolean(deleteTarget && unconfirmedDeletes.has(deleteTarget.id));
  const targetPresent = Boolean(deleteTarget && releases.some(release => release.id === deleteTarget.id
    && release.version_code === deleteTarget.version_code && release.sha256 === deleteTarget.sha256
    && release.platform === deleteTarget.platform && release.flavor === deleteTarget.flavor));

  const confirmDelete = async (readOnly: boolean) => {
    if (!canManage || !deleteTarget || deleteRequest.current || (!readOnly && (!targetPresent || isFetching || deleteUnknown))) return;
    const target = deleteTarget;
    const controller = new AbortController();
    deleteRequest.current = controller;
    setDeletePending(true);
    setDeleteError('');
    try {
      if (!readOnly) {
        const response = await api.delete(`/updates/${target.id}`, { signal: controller.signal });
        if (response.status !== 204) throw new Error('Unexpected delete status');
      }
      const snapshot = await refetch();
      if (controller.signal.aborted) return;
      if (!snapshot.isSuccess || !snapshot.data) throw new Error('Catalog refresh not confirmed');
      setUnconfirmedDeletes(previous => {
        const next = new Set(previous);
        next.delete(target.id);
        return next;
      });
      if (snapshot.data.releases.some(release => release.id === target.id)) {
        setDeleteError('Релиз ещё есть в каталоге. Проверьте выбранную запись перед повтором.');
        return;
      }
      setDeleteTarget(null);
      setNotice(`Релиз ${target.version_name} отсутствует в обновлённом каталоге.`);
    } catch (failure) {
      if (!controller.signal.aborted) {
        setUnconfirmedDeletes(previous => new Set(previous).add(target.id));
        setDeleteError(getApiErrorMessage(failure, 'Результат удаления неизвестен. Перечитайте каталог перед повтором.'));
      }
    } finally {
      deleteRequest.current = null;
      if (!controller.signal.aborted) setDeletePending(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Обновления и приложения</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Скачивайте агент, управляйте релизами и проверяйте доставку обновлений.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button ref={refreshButton} variant="outline" aria-disabled={isFetching} onClick={() => { if (!isFetching) void refetch(); }}>
            Обновить релизы
          </Button>
          {canManage && <CreateReleaseDialog available={!isPending && !isFetching && !isError} onCreated={() => { void refetch(); }} />}
        </div>
      </div>

      <AgentDownloadPanel releases={filtered ? [] : releases} available={canRead} />
      {notice && <p role="status" className="text-sm text-success">{notice}</p>}

      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-muted-foreground">
        Агенты обнаруживают опубликованный релиз при плановой проверке <strong>только при совпадении платформы и варианта сборки</strong>.
        Регистрация релиза не загружает сам APK. Для адресной установки используйте «Адресное OTA»;
        результат подтверждается ответом агента и установленной версией.
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <Select value={platformFilter} onValueChange={setPlatformFilter}>
          <SelectTrigger className="w-[180px]" aria-label="Фильтр по платформе">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все платформы</SelectItem>
            <SelectItem value="android">Android</SelectItem>
            <SelectItem value="android-canary">Android canary</SelectItem>
            <SelectItem value="pc">PC</SelectItem>
          </SelectContent>
        </Select>
        <Select value={flavorFilter} onValueChange={setFlavorFilter}>
          <SelectTrigger className="w-[160px]" aria-label="Фильтр по сборке">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все сборки</SelectItem>
            <SelectItem value="enterprise">enterprise</SelectItem>
            <SelectItem value="dev">dev</SelectItem>
          </SelectContent>
        </Select>
        <Badge variant="outline">
          {isError || isPending ? 'Количество релизов неизвестно' : `Релизов: ${data?.total ?? 0}`}
        </Badge>
      </div>

      {/* Content */}
      {isPending && !isError && <div role="status" className="text-muted-foreground">Загружаем релизы…</div>}
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
          {filtered ? 'По выбранным фильтрам релизов нет.' : 'Опубликованных релизов пока нет.'}
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
                    <Badge variant="destructive" className="text-xs">Обязательное</Badge>
                  )}
                </div>
                {release.platform === 'android-canary' && (
                  <div className="text-xs text-amber-500 mt-1">
                    Пилотный канал: обычные Android-агенты не проверяют его.
                  </div>
                )}
                <div className="text-xs text-muted-foreground mt-1">
                  Код {release.version_code} · Опубликован {new Date(release.created_at).toLocaleString('ru-RU')}
                </div>
                {release.changelog && (
                  <div className="text-sm mt-1 text-muted-foreground">{release.changelog}</div>
                )}
                <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
                  SHA-256: {release.sha256 || '—'}
                </div>
              </div>
              <div className="flex flex-wrap justify-end gap-2">
              {canRead && isManagedAndroidRelease(release) && <Button variant="outline" size="sm" disabled={isFetching || isError} onClick={() => setRecoveryRelease({ ...release })}>{canManage ? 'Адресное OTA' : 'Состояние OTA'}</Button>}
              {canManage && <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive shrink-0"
                disabled={isFetching}
                aria-label={`Удалить релиз ${release.version_name} · ${release.platform}/${release.flavor}`}
                onClick={(event) => {
                  deleteTrigger.current = event.currentTarget;
                  setNotice('');
                  setDeleteError('');
                  setDeleteTarget(release);
                }}
              >
                Удалить
              </Button>}
              </div>
            </div>

          </div>
        ))}
      </div>
      {recoveryRelease && <RecoveryDialog release={recoveryRelease} scope={scope} canManage={canManage}
        available={!isError && !isFetching && Boolean(releases.find(value => value.id === recoveryRelease.id && value.sha256 === recoveryRelease.sha256 && value.version_code === recoveryRelease.version_code && value.version_name === recoveryRelease.version_name && value.download_url === recoveryRelease.download_url && value.flavor === recoveryRelease.flavor && value.platform === recoveryRelease.platform))}
        onClose={() => setRecoveryRelease(null)} />}
      <Dialog open={deleteTarget !== null} onOpenChange={open => { if (!open && !deleteRequest.current) setDeleteTarget(null); }}>
        {deleteTarget && <DialogContent onCloseAutoFocus={event => {
          event.preventDefault();
          (deleteTrigger.current?.isConnected ? deleteTrigger.current : refreshButton.current)?.focus();
        }}>
          <DialogHeader>
            <DialogTitle>Удалить релиз из каталога?</DialogTitle>
            <DialogDescription>Агенты перестанут получать этот релиз при следующих проверках канала. Для уже установленных APK нужен отдельный процесс обновления.</DialogDescription>
          </DialogHeader>
          <p className="text-sm font-medium">{deleteTarget.version_name} · код {deleteTarget.version_code} · {deleteTarget.platform}/{deleteTarget.flavor}</p>
          {deleteError && <p role="alert" className="text-sm text-destructive">{deleteError}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={deletePending} onClick={() => setDeleteTarget(null)}>Отмена</Button>
            {deleteUnknown
              ? <Button type="button" disabled={deletePending} onClick={() => { void confirmDelete(true); }}>Перечитать каталог</Button>
              : <Button type="button" variant="destructive" disabled={deletePending || !targetPresent || isFetching} onClick={() => { void confirmDelete(false); }}>{deletePending ? 'Проверяем…' : 'Подтвердить удаление'}</Button>}
          </DialogFooter>
        </DialogContent>}
      </Dialog>
    </div>
  );
}
