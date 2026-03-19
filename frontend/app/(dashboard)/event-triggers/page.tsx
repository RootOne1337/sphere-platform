'use client';

import { useState, useMemo } from 'react';
import { toast } from 'sonner';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Zap,
  Plus,
  Trash2,
  Pencil,
  ToggleLeft,
  ToggleRight,
  Search,
  Clock,
  Activity,
  GitBranch,
  Loader2,
  ShieldAlert,
  Timer,
  RefreshCw,
} from 'lucide-react';
import {
  useEventTriggers,
  useCreateEventTrigger,
  useUpdateEventTrigger,
  useToggleEventTrigger,
  useDeleteEventTrigger,
  type EventTrigger,
  type CreateEventTriggerInput,
} from '@/lib/hooks/useEventTriggers';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

// ── Типы пайплайнов (для выпадающего списка) ─────────────────────────

interface PipelineOption {
  id: string;
  name: string;
  is_active: boolean;
}

function usePipelineOptions() {
  return useQuery<PipelineOption[]>({
    queryKey: ['pipelines-options'],
    queryFn: async () => {
      const { data } = await api.get('/pipelines?per_page=200');
      return (data.items ?? []).map((p: any) => ({
        id: p.id,
        name: p.name,
        is_active: p.is_active,
      }));
    },
    staleTime: 30_000,
  });
}

// ── Утилиты ──────────────────────────────────────────────────────────

function timeAgo(dateStr: string | null) {
  if (!dateStr) return '—';
  const diff = Date.now() - new Date(dateStr).getTime();
  if (diff < 60_000) return 'только что';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} мин назад`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} ч назад`;
  return new Date(dateStr).toLocaleDateString('ru-RU');
}

// ── Главная страница ─────────────────────────────────────────────────

export default function EventTriggersPage() {
  const [search, setSearch] = useState('');
  const [filterActive, setFilterActive] = useState<string>('__all__');
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EventTrigger | null>(null);

  const params = useMemo(() => ({
    per_page: 100,
    is_active: filterActive === 'true' ? true : filterActive === 'false' ? false : undefined,
  }), [filterActive]);

  const { data, isLoading, refetch } = useEventTriggers(params);
  const { data: pipelines = [] } = usePipelineOptions();
  const toggleMut = useToggleEventTrigger();
  const deleteMut = useDeleteEventTrigger();

  const triggers = data?.items ?? [];

  const filtered = useMemo(() => {
    if (!search.trim()) return triggers;
    const q = search.toLowerCase();
    return triggers.filter(t =>
      (t.name || '').toLowerCase().includes(q) ||
      (t.event_type_pattern || '').toLowerCase().includes(q) ||
      (t.description || '').toLowerCase().includes(q),
    );
  }, [triggers, search]);

  const pipelineMap = useMemo(() => {
    const m = new Map<string, string>();
    pipelines.forEach(p => m.set(p.id, p.name));
    return m;
  }, [pipelines]);

  return (
    <div className="flex flex-col h-full bg-card">
      {/* ── HEADER ─────────────────────────────────────────────────── */}
      <div className="px-6 py-5 border-b border-border bg-muted shrink-0">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Zap className="w-5 h-5 text-primary" />
              <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">
                Event Triggers
              </h1>
              <Badge variant="outline" className="ml-2 text-[9px]">
                {triggers.length}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground font-mono max-w-2xl">
              Автоматический запуск Pipeline при наступлении событий. Паттерны glob: account.banned, task.*, device.offline.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
              <Input
                placeholder="Поиск триггеров..."
                className="pl-9 h-9 bg-black/50 border-border font-mono text-xs focus-visible:ring-primary/50"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <Select value={filterActive} onValueChange={setFilterActive}>
              <SelectTrigger className="h-9 w-[140px] text-xs font-mono">
                <SelectValue placeholder="Все" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">Все</SelectItem>
                <SelectItem value="true">Активные</SelectItem>
                <SelectItem value="false">Неактивные</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" className="h-9" onClick={() => refetch()}>
              <RefreshCw className="w-3.5 h-3.5 mr-1" /> Обновить
            </Button>
            <Button size="sm" className="h-9 font-mono text-xs uppercase tracking-wider" onClick={() => setCreateOpen(true)}>
              <Plus className="w-3.5 h-3.5 mr-1.5" /> Создать триггер
            </Button>
          </div>
        </div>
      </div>

      {/* ── STATS ──────────────────────────────────────────────────── */}
      <div className="px-6 pt-5">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          <StatCard label="Всего триггеров" value={triggers.length} icon={<Zap className="w-7 h-7 text-primary/30" strokeWidth={1} />} />
          <StatCard label="Активных" value={triggers.filter(t => t.is_active).length} icon={<Activity className="w-7 h-7 text-success/30" strokeWidth={1} />} />
          <StatCard label="Сработало (всего)" value={triggers.reduce((s, t) => s + t.total_triggers, 0)} icon={<GitBranch className="w-7 h-7 text-primary/30" strokeWidth={1} />} />
          <StatCard label="С ошибками" value={triggers.filter(t => !t.is_active && t.total_triggers > 0).length} icon={<ShieldAlert className="w-7 h-7 text-destructive/30" strokeWidth={1} />} />
        </div>
      </div>

      {/* ── ТАБЛИЦА ────────────────────────────────────────────────── */}
      <div className="px-6 flex-1 overflow-auto pb-6">
        <div className="rounded-sm border border-border bg-card shadow-2xl overflow-x-auto">
          <table className="w-full text-left whitespace-nowrap">
            <thead className="bg-[#151515]/90 border-b border-border text-[10px] uppercase font-mono tracking-widest font-bold text-muted-foreground sticky top-0 backdrop-blur-sm z-10">
              <tr>
                <th className="px-4 py-3 w-[50px]">Статус</th>
                <th className="px-4 py-3">Имя</th>
                <th className="px-4 py-3">Паттерн</th>
                <th className="px-4 py-3">Pipeline</th>
                <th className="px-4 py-3 w-[100px]">Cooldown</th>
                <th className="px-4 py-3 w-[100px]">Лимит/ч</th>
                <th className="px-4 py-3 w-[100px]">Сработал</th>
                <th className="px-4 py-3 w-[130px]">Последний</th>
                <th className="px-4 py-3 w-[120px] text-right">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#222]/50 font-mono text-xs text-foreground/80">
              {isLoading && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-muted-foreground">
                    <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" /> Загрузка...
                  </td>
                </tr>
              )}
              {!isLoading && filtered.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-muted-foreground">
                    <Zap className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    {search ? 'Ничего не найдено' : 'Нет триггеров. Создайте первый!'}
                  </td>
                </tr>
              )}
              {filtered.map((t) => (
                <tr key={t.id} className="hover:bg-muted transition-colors group">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className={`w-1.5 h-1.5 rounded-full ${t.is_active ? 'bg-success animate-pulse' : 'bg-muted-foreground'}`} />
                      <span className={`text-[10px] font-bold tracking-widest ${t.is_active ? 'text-success' : 'text-muted-foreground'}`}>
                        {t.is_active ? 'ON' : 'OFF'}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-bold text-foreground">{t.name}</div>
                    {t.description && (
                      <div className="text-[10px] text-muted-foreground mt-0.5 max-w-[250px] truncate">{t.description}</div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="outline" className="text-[9px] border-primary/50 text-primary font-mono">
                      {t.event_type_pattern}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-foreground">{pipelineMap.get(t.pipeline_id) ?? t.pipeline_id.slice(0, 8)}</span>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    <div className="flex items-center gap-1">
                      <Timer className="w-3 h-3" /> {t.cooldown_seconds}с
                    </div>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{t.max_triggers_per_hour || '∞'}</td>
                  <td className="px-4 py-3">
                    <span className="font-bold text-foreground">{t.total_triggers}</span>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{timeAgo(t.last_triggered_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className={`h-7 w-7 ${t.is_active
                          ? 'text-success hover:text-warning hover:bg-warning/10'
                          : 'text-muted-foreground hover:text-success hover:bg-success/10'
                        }`}
                        title={t.is_active ? 'Деактивировать' : 'Активировать'}
                        onClick={() => toggleMut.mutate(t.id, {
                          onSuccess: () => toast.success(t.is_active ? 'Триггер деактивирован' : 'Триггер активирован'),
                          onError: () => toast.error('Ошибка переключения'),
                        })}
                        disabled={toggleMut.isPending}
                      >
                        {t.is_active ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-primary hover:bg-primary/10"
                        title="Редактировать"
                        onClick={() => setEditTarget(t)}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                        title="Удалить"
                        onClick={() => {
                          if (confirm(`Удалить триггер "${t.name}"?`)) {
                            deleteMut.mutate(t.id, {
                              onSuccess: () => toast.success('Триггер удалён'),
                              onError: () => toast.error('Ошибка удаления'),
                            });
                          }
                        }}
                        disabled={deleteMut.isPending}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Диалог создания ─────────────────────────────────────── */}
      <TriggerFormDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        pipelines={pipelines}
        mode="create"
      />

      {/* ── Диалог редактирования ───────────────────────────────── */}
      {editTarget && (
        <TriggerFormDialog
          open={!!editTarget}
          onClose={() => setEditTarget(null)}
          pipelines={pipelines}
          mode="edit"
          trigger={editTarget}
        />
      )}
    </div>
  );
}

// ── Stat Card ────────────────────────────────────────────────────────

function StatCard({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return (
    <div className="border border-border bg-muted rounded-sm p-4 flex items-center justify-between">
      <div>
        <div className="text-[10px] uppercase text-muted-foreground font-bold tracking-widest mb-1">{label}</div>
        <div className="text-2xl font-mono font-bold text-foreground">{value}</div>
      </div>
      {icon}
    </div>
  );
}

// ── Форма создания / редактирования ──────────────────────────────────

interface TriggerFormDialogProps {
  open: boolean;
  onClose: () => void;
  pipelines: PipelineOption[];
  mode: 'create' | 'edit';
  trigger?: EventTrigger;
}

function TriggerFormDialog({ open, onClose, pipelines, mode, trigger }: TriggerFormDialogProps) {
  const createMut = useCreateEventTrigger();
  const updateMut = useUpdateEventTrigger();

  const [name, setName] = useState(trigger?.name ?? '');
  const [description, setDescription] = useState(trigger?.description ?? '');
  const [pattern, setPattern] = useState(trigger?.event_type_pattern ?? '');
  const [pipelineId, setPipelineId] = useState(trigger?.pipeline_id ?? '');
  const [cooldown, setCooldown] = useState(trigger?.cooldown_seconds ?? 60);
  const [maxPerHour, setMaxPerHour] = useState(trigger?.max_triggers_per_hour ?? 100);
  const [paramsJson, setParamsJson] = useState(
    trigger?.input_params_template ? JSON.stringify(trigger.input_params_template, null, 2) : '{}',
  );

  const isSubmitting = createMut.isPending || updateMut.isPending;

  const handleSubmit = () => {
    let parsedParams: Record<string, unknown> = {};
    try {
      parsedParams = JSON.parse(paramsJson);
    } catch {
      toast.error('Невалидный JSON в шаблоне параметров');
      return;
    }

    if (!name.trim() || !pattern.trim() || !pipelineId) {
      toast.error('Заполните все обязательные поля');
      return;
    }

    if (mode === 'create') {
      createMut.mutate(
        {
          name: name.trim(),
          description: description.trim() || undefined,
          event_type_pattern: pattern.trim(),
          pipeline_id: pipelineId,
          input_params_template: parsedParams,
          cooldown_seconds: cooldown,
          max_triggers_per_hour: maxPerHour,
        },
        {
          onSuccess: () => {
            toast.success('Триггер создан');
            onClose();
          },
          onError: (err: any) => {
            toast.error(err?.response?.data?.detail || 'Ошибка создания');
          },
        },
      );
    } else if (trigger) {
      updateMut.mutate(
        {
          id: trigger.id,
          name: name.trim(),
          description: description.trim() || undefined,
          event_type_pattern: pattern.trim(),
          pipeline_id: pipelineId,
          input_params_template: parsedParams,
          cooldown_seconds: cooldown,
          max_triggers_per_hour: maxPerHour,
        },
        {
          onSuccess: () => {
            toast.success('Триггер обновлён');
            onClose();
          },
          onError: (err: any) => {
            toast.error(err?.response?.data?.detail || 'Ошибка обновления');
          },
        },
      );
    }
  };

  const PATTERN_EXAMPLES = [
    'account.banned',
    'account.*',
    'task.failed',
    'task.*',
    'device.offline',
    'device.*',
  ];

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 font-mono text-sm uppercase tracking-widest">
            <Zap className="w-4 h-4 text-primary" />
            {mode === 'create' ? 'Создать Event Trigger' : 'Редактировать Trigger'}
          </DialogTitle>
          <DialogDescription className="text-xs font-mono">
            Триггер автоматически запускает Pipeline при наступлении события.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 pt-2">
          {/* Имя */}
          <div className="space-y-1">
            <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
              Имя *
            </Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Бан → Ротация аккаунта"
              className="font-mono text-xs"
            />
          </div>

          {/* Описание */}
          <div className="space-y-1">
            <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
              Описание
            </Label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Авто-ротация аккаунта при бане"
              className="font-mono text-xs"
            />
          </div>

          {/* Паттерн */}
          <div className="space-y-1">
            <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
              Event Type Pattern (Glob) *
            </Label>
            <Input
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
              placeholder="account.banned"
              className="font-mono text-xs"
            />
            <div className="flex flex-wrap gap-1 mt-1">
              {PATTERN_EXAMPLES.map(p => (
                <Badge
                  key={p}
                  variant="outline"
                  className="text-[9px] cursor-pointer hover:bg-primary/10 hover:border-primary/50"
                  onClick={() => setPattern(p)}
                >
                  {p}
                </Badge>
              ))}
            </div>
          </div>

          {/* Pipeline */}
          <div className="space-y-1">
            <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
              Pipeline для запуска *
            </Label>
            <Select value={pipelineId} onValueChange={setPipelineId}>
              <SelectTrigger className="text-xs font-mono">
                <SelectValue placeholder="Выберите pipeline..." />
              </SelectTrigger>
              <SelectContent>
                {pipelines.length === 0 && (
                  <SelectItem value="__none__" disabled>Нет доступных pipelines</SelectItem>
                )}
                {pipelines.map(p => (
                  <SelectItem key={p.id} value={p.id}>
                    <span className="flex items-center gap-2">
                      <GitBranch className="w-3 h-3" />
                      {p.name}
                      {!p.is_active && <Badge variant="secondary" className="text-[8px] ml-1">INACTIVE</Badge>}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Cooldown + Rate limit */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
                Cooldown (сек)
              </Label>
              <Input
                type="number"
                min={0}
                value={cooldown}
                onChange={(e) => setCooldown(Number(e.target.value))}
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
                Макс. в час (0 = ∞)
              </Label>
              <Input
                type="number"
                min={0}
                value={maxPerHour}
                onChange={(e) => setMaxPerHour(Number(e.target.value))}
                className="font-mono text-xs"
              />
            </div>
          </div>

          {/* JSON Template */}
          <div className="space-y-1">
            <Label className="text-[10px] uppercase tracking-widest font-mono font-bold text-muted-foreground">
              Шаблон параметров (JSON)
            </Label>
            <textarea
              value={paramsJson}
              onChange={(e) => setParamsJson(e.target.value)}
              rows={4}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-xs font-mono ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring"
              placeholder='{"device_id": "{device_id}", "reason": "{event_type}"}'
            />
            <p className="text-[10px] text-muted-foreground">
              Плейсхолдеры: {'{device_id}'}, {'{account_id}'}, {'{event_type}'}, {'{event_id}'}
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Отмена
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
            {mode === 'create' ? 'Создать' : 'Сохранить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
