'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { Loader2, Play, Users, Monitor, ListChecks } from 'lucide-react';

import { api } from '@/lib/api';
import { useGroups } from '@/lib/hooks/useGroups';
import { useDevices, type Device } from '@/lib/hooks/useDevices';
import { useCreateTask } from '@/lib/hooks/useTasks';
import { useStartBatch } from '@/lib/hooks/useBatches';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
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

interface RunScriptModalProps {
  scriptId: string;
  scriptName: string;
  open: boolean;
  onClose: () => void;
}

// ─── Component ──────────────────────────────────────────────────────────────

export function RunScriptModal({
  scriptId,
  scriptName,
  open,
  onClose,
}: RunScriptModalProps) {
  const router = useRouter();
  const qc = useQueryClient();

  // Target selection state
  const [targetMode, setTargetMode] = useState<TargetMode>('all');
  const [selectedGroupId, setSelectedGroupId] = useState<string>('');
  const [selectedDeviceIds, setSelectedDeviceIds] = useState<Set<string>>(new Set());

  // Options state
  const [priority, setPriority] = useState(5);
  const [waveSize, setWaveSize] = useState(10);
  const [waveDelayMs, setWaveDelayMs] = useState(5000);

  // Result state
  const [error, setError] = useState<string | null>(null);

  // Data fetching
  const { data: groups } = useGroups();
  const { data: allDevicesData, isLoading: devicesLoading } = useDevices({
    page_size: 5000,
    group_id: targetMode === 'group' && selectedGroupId ? selectedGroupId : undefined,
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
    return allDevices.length;
  }

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
    setError(null);
    const deviceIds = getTargetDeviceIds();

    if (deviceIds.length === 0) {
      setError('Не выбрано ни одного устройства');
      return;
    }

    try {
      if (deviceIds.length === 1) {
        // Single device → create direct task
        const task = await createTask.mutateAsync({
          script_id: scriptId,
          device_id: deviceIds[0],
          priority,
        });
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
        });
        qc.invalidateQueries({ queryKey: ['tasks'] });
        onClose();
        router.push(`/tasks?batch_id=${batch.id}`);
      }
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Ошибка запуска скрипта';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
  }

  const isSubmitting = createTask.isPending || startBatch.isPending;
  const targetCount = getTargetCount();

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Play className="w-4 h-4 text-green-500" />
            Запустить: {scriptName}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-5">
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
              {devicesLoading ? (
                <p className="text-xs text-muted-foreground py-2">Загрузка…</p>
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
            </div>
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
            <p className="text-sm text-destructive rounded border border-destructive/40 bg-destructive/10 px-3 py-2">
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
              isSubmitting ||
              (targetMode === 'group' && !selectedGroupId) ||
              (targetMode === 'select' && selectedDeviceIds.size === 0) ||
              devicesLoading
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
