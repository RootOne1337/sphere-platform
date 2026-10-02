'use client';

import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Loader2, Play, Users, Monitor, ListChecks } from 'lucide-react';

import { useGroups } from '@/lib/hooks/useGroups';
import { useDevices, type Device } from '@/lib/hooks/useDevices';
import { useCreateTask } from '@/lib/hooks/useTasks';
import { useStartBatch } from '@/lib/hooks/useBatches';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';

// ─── Types ──────────────────────────────────────────────────────────────────

type TargetMode = 'all' | 'group' | 'select';
const MAX_BATCH_TARGETS = 1000;

interface RunScriptModalProps {
  scriptId: string;
  scriptName: string;
  open: boolean;
  onClose: () => void;
  expectedVersion?: { id: string; version: number; dag_hash: string | null };
  requireVersion?: boolean;
}

// ─── Component ──────────────────────────────────────────────────────────────

export function RunScriptModal({
  scriptId,
  scriptName,
  open,
  onClose,
  expectedVersion,
  requireVersion = false,
}: RunScriptModalProps) {
  const router = useRouter();
  const qc = useQueryClient();

  // Target selection state
  const [targetMode, setTargetMode] = useState<TargetMode>('all');
  const [selectedGroupId, setSelectedGroupId] = useState<string>('');
  const [selectedDeviceIds, setSelectedDeviceIds] = useState<Set<string>>(new Set());
  const [deviceSearch, setDeviceSearch] = useState('');
  const [debouncedDeviceSearch, setDebouncedDeviceSearch] = useState('');

  // Options state
  const [priority, setPriority] = useState(5);
  const [waveSize, setWaveSize] = useState(10);
  const [waveDelayMs, setWaveDelayMs] = useState(5000);

  // Result state
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const busy = useRef(false);
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const versionUnavailable = requireVersion && (!expectedVersion?.id || !expectedVersion.dag_hash);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedDeviceSearch(deviceSearch.trim()), 300);
    return () => window.clearTimeout(timeout);
  }, [deviceSearch]);

  // Data fetching
  const { data: groups } = useGroups();
  const { data: allDevicesData, isLoading: devicesLoading, isError: devicesLoadError } = useDevices({
    page_size: MAX_BATCH_TARGETS,
    group_id: targetMode === 'group' && selectedGroupId ? selectedGroupId : undefined,
    search: targetMode === 'select' && debouncedDeviceSearch ? debouncedDeviceSearch : undefined,
  });
  const allDevices: Device[] = allDevicesData?.items ?? [];

  const createTask = useCreateTask();
  const startBatch = useStartBatch();

  // ── Helpers ──────────────────────────────────────────────────────────────

  function getTargetDeviceIds(): string[] {
    if (targetMode === 'all') return allDevices.map((d) => d.id);
    if (targetMode === 'group') return allDevices.map((d) => d.id);
    return Array.from(selectedDeviceIds);
  }

  function getTargetCount(): number {
    if (targetMode === 'select') return selectedDeviceIds.size;
    if (targetMode === 'group' && !selectedGroupId) return 0;
    return allDevicesData?.total ?? allDevices.length;
  }

  const targetCount = getTargetCount();
  const hasResolvedScope = targetMode === 'all' || (targetMode === 'group' && Boolean(selectedGroupId));
  const scopeIsIncomplete = hasResolvedScope && Boolean(allDevicesData) && (
    targetCount > MAX_BATCH_TARGETS || (allDevicesData?.items.length ?? 0) < targetCount
  );
  const scopeOverBatchLimit = hasResolvedScope && targetCount > MAX_BATCH_TARGETS;

  function toggleDevice(id: string) {
    setSelectedDeviceIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // ── Submit ───────────────────────────────────────────────────────────────

  async function handleRun() {
    if (busy.current || uncertain || versionUnavailable) return;
    setError(null);
    if (devicesLoading || devicesLoadError || scopeIsIncomplete) {
      setError('Список устройств неполный или недоступен. Уточните цель и повторите после загрузки полного списка.');
      return;
    }
    if (targetCount > MAX_BATCH_TARGETS) {
      setError(`За один запуск поддерживается не более ${MAX_BATCH_TARGETS} устройств.`);
      return;
    }
    const deviceIds = getTargetDeviceIds();

    if (deviceIds.length === 0) {
      setError('Не выбрано ни одного устройства');
      return;
    }

    busy.current = true; setPending(true);
    try {
      if (deviceIds.length === 1) {
        // Single device → create direct task
        const task = await createTask.mutateAsync({
          script_id: scriptId,
          device_id: deviceIds[0],
          priority,
          ...(expectedVersion ? { expected_current_version_id: expectedVersion.id } : {}),
        });
        if (expectedVersion && (task?.script_version_id !== expectedVersion.id || task.script_id !== scriptId || task.device_id !== deviceIds[0])) throw new Error('Unconfirmed task receipt');
        if (!live.current) return;
        qc.invalidateQueries({ queryKey: ['tasks'] });
        onClose();
        router.push(`/tasks/${task.id}`);
      } else {
        // Multiple devices → batch
        const batch = await startBatch.mutateAsync({
          script_id: scriptId,
          device_ids: deviceIds,
          wave_size: waveSize,
          wave_delay_ms: waveDelayMs,
          priority,
          name: `${scriptName} — batch`,
          ...(expectedVersion ? { expected_current_version_id: expectedVersion.id } : {}),
        });
        if (expectedVersion && (batch.script_version_id !== expectedVersion.id || batch.script_id !== scriptId || batch.total !== deviceIds.length)) throw new Error('Unconfirmed batch receipt');
        if (!live.current) return;
        qc.invalidateQueries({ queryKey: ['tasks'] });
        onClose();
        router.push(`/tasks?batch_id=${batch.id}`);
      }
    } catch (err: unknown) {
      if (!live.current) return;
      if (requireVersion) {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 409) setError('Версия сценария изменилась или устройство занято. Закройте окно, обновите каталог и подтвердите запуск заново.');
        else if (status && status >= 400 && status < 500) setError('Сервер отклонил запуск. Проверьте доступ, сценарий и выбранные устройства.');
        else { setUncertain(true); setError('Результат запуска неизвестен. Проверьте журнал заданий перед новым запуском.'); }
        return;
      }
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Ошибка запуска скрипта';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      busy.current = false;
      if (live.current) setPending(false);
    }
  }

  const isSubmitting = pending || createTask.isPending || startBatch.isPending;
  const listIsPartial = Boolean(allDevicesData && allDevicesData.items.length < allDevicesData.total);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v && !busy.current) onClose(); }}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Play className="w-4 h-4 text-green-500" />
            Запустить: {scriptName}
          </DialogTitle>
          <DialogDescription>
            Выберите полный набор устройств. Массовый запуск ограничен сервером максимумом в {MAX_BATCH_TARGETS} целей.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {expectedVersion && <div className="space-y-1 rounded-lg border bg-muted/30 p-3 text-sm"><p className="font-medium">Версия для запуска: v{expectedVersion.version}</p><p className="break-all font-mono text-xs">SHA-256: {expectedVersion.dag_hash ?? 'Не сообщён'}</p><p className="text-xs text-muted-foreground">Сервер проверит эту версию до создания заданий. При изменении сценария запуск будет отклонён.</p></div>}
          {versionUnavailable && <p role="alert" className="text-sm text-destructive">Версия сценария не подтверждена. Обновите каталог перед запуском.</p>}
          {uncertain && <Link className="text-sm text-primary underline" href="/tasks">Открыть журнал заданий</Link>}
          {/* ── Target mode ─────────────────────────────────────────── */}
          <div className="space-y-2">
            <Label className="text-sm font-medium">Целевые устройства</Label>
            <div className="grid grid-cols-3 gap-2">
              {(
                [
                  { value: 'all', label: 'Все устройства', Icon: Monitor },
                  { value: 'group', label: 'По группе', Icon: Users },
                  { value: 'select', label: 'Выбрать', Icon: ListChecks },
                ] as const
              ).map(({ value, label, Icon }) => (
                <button
                  key={value}
                  onClick={() => {
                    setTargetMode(value);
                    setSelectedDeviceIds(new Set());
                  }}
                  className={`flex flex-col items-center gap-1 rounded-lg border p-3 text-xs transition-colors ${
                    targetMode === value
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border hover:bg-accent/50'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* ── Group picker ─────────────────────────────────────────── */}
          {targetMode === 'group' && (
            <div className="space-y-1.5">
              <Label htmlFor="group-select">Группа</Label>
              <Select
                value={selectedGroupId}
                onValueChange={setSelectedGroupId}
              >
                <SelectTrigger id="group-select">
                  <SelectValue placeholder="Выберите группу…" />
                </SelectTrigger>
                <SelectContent>
                  {groups?.map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      {g.name}
                      <span className="ml-2 text-xs text-muted-foreground">
                        ({g.online_devices}/{g.total_devices} online)
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* ── Device checklist ─────────────────────────────────────── */}
          {targetMode === 'select' && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label>Устройства</Label>
                {selectedDeviceIds.size > 0 && (
                  <Badge variant="secondary">{selectedDeviceIds.size} выбрано</Badge>
                )}
              </div>
              <Input
                aria-label="Поиск устройств"
                value={deviceSearch}
                onChange={(event) => setDeviceSearch(event.target.value)}
                placeholder="Имя, Android ID или модель"
              />
              {devicesLoading ? (
                <p className="text-xs text-muted-foreground py-2">Загрузка…</p>
              ) : devicesLoadError ? (
                <p role="alert" className="text-xs text-destructive py-2">
                  Не удалось загрузить каталог устройств. Запуск заблокирован.
                </p>
              ) : (
                <div className="max-h-52 overflow-y-auto rounded border divide-y">
                  {allDevices.length === 0 ? (
                    <p className="text-xs text-muted-foreground p-3 text-center">
                      Нет устройств
                    </p>
                  ) : (
                    allDevices.map((device) => (
                      <label
                        key={device.id}
                        className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-accent/40 text-sm"
                      >
                        <Checkbox
                          checked={selectedDeviceIds.has(device.id)}
                          onCheckedChange={() => toggleDevice(device.id)}
                        />
                        <span className="flex-1 truncate">{device.name || device.android_id}</span>
                        <span
                          className={`text-xs ${
                            device.status === 'online'
                              ? 'text-green-500'
                              : 'text-muted-foreground'
                          }`}
                        >
                          {device.status}
                        </span>
                      </label>
                    ))
                  )}
                </div>
              )}
              {listIsPartial && !devicesLoadError && (
                <p role="status" className="text-xs text-muted-foreground">
                  Показаны первые {allDevices.length} из {allDevicesData?.total}. Уточните поиск; запуск включает только отмеченные устройства.
                </p>
              )}
            </div>
          )}

          {scopeIsIncomplete && (
            <p role="alert" className="text-sm text-destructive rounded border border-destructive/40 bg-destructive/10 px-3 py-2">
              {scopeOverBatchLimit
                ? `В выбранной области ${targetCount} устройств, а один запуск поддерживает максимум ${MAX_BATCH_TARGETS}. Ничего не отправлено: сузьте область или выберите до ${MAX_BATCH_TARGETS} устройств вручную.`
                : `API вернул неполный список для области из ${targetCount} устройств. Ничего не отправлено; обновите каталог и повторите.`}
            </p>
          )}

          {devicesLoadError && targetMode !== 'select' && (
            <p role="alert" className="text-sm text-destructive rounded border border-destructive/40 bg-destructive/10 px-3 py-2">
              Не удалось загрузить каталог устройств. Запуск заблокирован.
            </p>
          )}

          {/* ── Options ──────────────────────────────────────────────── */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="priority">Приоритет (1–10)</Label>
              <input
                id="priority"
                type="number"
                min={1}
                max={10}
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                className="w-full rounded-md border bg-background px-3 py-2 text-sm"
              />
            </div>
            {targetCount !== 1 && (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="wave-size">Размер волны</Label>
                  <input
                    id="wave-size"
                    type="number"
                    min={1}
                    max={100}
                    value={waveSize}
                    onChange={(e) => setWaveSize(Number(e.target.value))}
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  />
                </div>
                <div className="space-y-1.5 col-span-2">
                  <Label htmlFor="wave-delay">Задержка волны (мс)</Label>
                  <input
                    id="wave-delay"
                    type="number"
                    min={0}
                    max={3_600_000}
                    step={500}
                    value={waveDelayMs}
                    onChange={(e) => setWaveDelayMs(Number(e.target.value))}
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  />
                </div>
              </>
            )}
          </div>

          {/* ── Error ────────────────────────────────────────────────── */}
          {error && (
            <p role="alert" className="text-sm text-destructive rounded border border-destructive/40 bg-destructive/10 px-3 py-2">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Отмена
          </Button>
          <Button
            onClick={handleRun}
            disabled={
              isSubmitting || uncertain || versionUnavailable ||
              (targetMode === 'group' && !selectedGroupId) ||
              (targetMode === 'select' && selectedDeviceIds.size === 0) ||
              devicesLoading ||
              devicesLoadError ||
              scopeIsIncomplete ||
              targetCount > MAX_BATCH_TARGETS ||
              (hasResolvedScope && targetCount === 0)
            }
            className="gap-2"
          >
            {isSubmitting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            {isSubmitting
              ? 'Запуск…'
              : targetCount > 0
              ? `Запустить на ${targetCount} уст.`
              : 'Запустить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
