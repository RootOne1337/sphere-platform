'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAssignVpn, useBulkRevokeVpn } from '@/lib/hooks/useVpn';
import { useDevices } from '@/lib/hooks/useDevices';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';

const MAX_VPN_BATCH_TARGETS = 500;

type BatchOutcome = {
  kind: 'success' | 'warning' | 'error';
  message: string;
};

export function VpnBatchTab() {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [processing, setProcessing] = useState(false);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [outcome, setOutcome] = useState<BatchOutcome | null>(null);
  const [progress, setProgress] = useState<{ completed: number; total: number } | null>(null);
  const queryClient = useQueryClient();
  const { data, isLoading, isError, refetch } = useDevices({
    page_size: MAX_VPN_BATCH_TARGETS,
    search: debouncedSearch || undefined,
  });
  const assignVpn = useAssignVpn({ invalidateOnSuccess: false });
  const bulkRevokeVpn = useBulkRevokeVpn();

  const devices = data?.items ?? [];
  const listIsPartial = Boolean(data && data.items.length < data.total);
  const isBusy = processing || assignVpn.isPending || bulkRevokeVpn.isPending;

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timeout);
  }, [search]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < MAX_VPN_BATCH_TARGETS) next.add(id);
      return next;
    });
    setOutcome(null);
  };

  const handleBatchAssign = useCallback(async () => {
    const targets = Array.from(selected);
    if (targets.length === 0 || targets.length > MAX_VPN_BATCH_TARGETS || isError) return;

    setProcessing(true);
    setOutcome(null);
    setProgress({ completed: 0, total: targets.length });
    const failedIds = new Set<string>();
    let succeeded = 0;

    try {
      // Assign has no bulk endpoint. Keep the requests serial to avoid flooding the provider.
      for (const [index, deviceId] of targets.entries()) {
        try {
          await assignVpn.mutateAsync({ device_id: deviceId });
          succeeded += 1;
        } catch {
          // A timeout can leave the remote outcome uncertain; retain only this ID for review.
          failedIds.add(deviceId);
        }
        setProgress({ completed: index + 1, total: targets.length });
      }

      setSelected(failedIds);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ['vpn'] }),
        queryClient.invalidateQueries({ queryKey: ['devices'] }),
      ]);
      setOutcome({
        kind: failedIds.size ? 'warning' : 'success',
        message: failedIds.size
          ? `Назначено ${succeeded} из ${targets.length}. Для ${failedIds.size} устройств результат не подтверждён; проверьте список пиров перед повтором.`
          : `VPN назначен на ${succeeded} устройств.`,
      });
    } finally {
      setProcessing(false);
      setProgress(null);
    }
  }, [assignVpn, isError, queryClient, selected]);

  const handleBatchRevoke = useCallback(async () => {
    const targets = Array.from(selected);
    if (targets.length === 0 || targets.length > MAX_VPN_BATCH_TARGETS || isError) return;

    setProcessing(true);
    setOutcome(null);
    setProgress({ completed: 0, total: targets.length });

    try {
      const result = await bulkRevokeVpn.mutateAsync(targets);
      const resultById = new Map(result.results.map((item) => [item.device_id, item]));
      const unresolvedIds = targets.filter((deviceId) => resultById.get(deviceId)?.success !== true);
      const targetIds = new Set(targets);
      const receiptIds = result.results.map((item) => item.device_id);
      const receiptsComplete = result.total === targets.length &&
        result.results.length === targets.length &&
        new Set(receiptIds).size === targets.length &&
        receiptIds.every((deviceId) => targetIds.has(deviceId));
      const succeeded = result.results.filter((item) => targetIds.has(item.device_id) && item.success).length;
      const retrySelection = receiptsComplete ? unresolvedIds : targets;

      setSelected(new Set(retrySelection));
      setOutcome({
        kind: retrySelection.length || !receiptsComplete ? 'warning' : 'success',
        message: !receiptsComplete
          ? `Получен неполный receipt: подтверждено ${succeeded} из ${targets.length}. Весь набор оставлен для сверки; проверьте peers перед повтором.`
          : unresolvedIds.length
          ? `Отозвано ${succeeded} из ${targets.length}. Для ${unresolvedIds.length} устройств операция не подтверждена; проверьте peers перед повтором.`
          : `VPN отозван у ${succeeded} устройств.`,
      });
      setProgress({ completed: targets.length, total: targets.length });
    } catch {
      // Do not retry a mutation whose server-side outcome was not received.
      setOutcome({
        kind: 'error',
        message: 'Сервер не подтвердил результат отзыва. Проверьте состояние peers перед повторным запуском.',
      });
    } finally {
      setProcessing(false);
      setProgress(null);
    }
  }, [bulkRevokeVpn, isError, selected]);

  return (
    <div className="mt-4 space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Input
          aria-label="Поиск устройств для VPN"
          placeholder="Имя, Android ID или модель"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="sm:max-w-sm"
          disabled={isBusy}
        />
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            disabled={selected.size === 0 || selected.size > MAX_VPN_BATCH_TARGETS || isBusy || isLoading || isError}
            onClick={handleBatchAssign}
          >
            {isBusy ? 'Обработка…' : `Назначить VPN (${selected.size})`}
          </Button>
          <Button
            variant="destructive"
            disabled={selected.size === 0 || selected.size > MAX_VPN_BATCH_TARGETS || isBusy || isLoading || isError}
            onClick={handleBatchRevoke}
          >
            {isBusy ? 'Обработка…' : `Отозвать VPN (${selected.size})`}
          </Button>
          {isError && <Button variant="outline" onClick={() => void refetch()}>Повторить загрузку</Button>}
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        До {MAX_VPN_BATCH_TARGETS} выбранных устройств. Назначение выполняется последовательно; отзыв использует backend bulk API с результатом по каждому устройству.
      </p>

      {outcome && (
        <p
          role={outcome.kind === 'error' ? 'alert' : 'status'}
          className={`rounded border px-3 py-2 text-sm ${
            outcome.kind === 'success'
              ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-700'
              : outcome.kind === 'warning'
              ? 'border-amber-500/30 bg-amber-500/5 text-amber-800'
              : 'border-destructive/40 bg-destructive/10 text-destructive'
          }`}
        >
          {outcome.message}
        </p>
      )}

      {progress && (
        <p role="status" aria-live="polite" className="text-xs text-muted-foreground">
          Обработано {progress.completed} из {progress.total}
        </p>
      )}

      {isError ? (
        <p role="alert" className="text-sm text-destructive">Не удалось загрузить каталог устройств.</p>
      ) : isLoading ? (
        <p role="status" className="text-sm text-muted-foreground">Загрузка устройств…</p>
      ) : (
        <>
          {listIsPartial && (
            <p role="status" className="text-xs text-muted-foreground">
              Показаны первые {devices.length} из {data?.total}. Уточните поиск; массовое действие применяется только к отмеченным устройствам.
            </p>
          )}
          <div className="space-y-1 max-h-96 overflow-auto">
            {devices.map((device) => (
              <label
                key={device.id}
                className="flex items-center gap-3 p-2 rounded hover:bg-accent cursor-pointer"
              >
                <Checkbox
                  checked={selected.has(device.id)}
                  disabled={isBusy || (!selected.has(device.id) && selected.size >= MAX_VPN_BATCH_TARGETS)}
                  onCheckedChange={() => toggle(device.id)}
                />
                <span className="text-sm">{device.name}</span>
                <span className="text-xs text-muted-foreground ml-auto">
                  {device.vpn_assigned ? 'VPN назначен' : 'VPN не назначен'}
                </span>
              </label>
            ))}
            {devices.length === 0 && (
              <p role="status" className="p-4 text-center text-sm text-muted-foreground">
                Устройства по этому запросу не найдены.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
