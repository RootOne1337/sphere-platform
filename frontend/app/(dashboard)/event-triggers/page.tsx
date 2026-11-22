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
  DialogBody,
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
} from '@/lib/hooks/useEventTriggers';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { CatalogPagination } from '@/src/shared/ui/catalog-pagination';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';
import { PermissionNotice, useCapabilities } from '@/src/features/access/Capabilities';
import { getApiErrorMessage } from '@/lib/apiError';
import { TriggerSimulation } from '@/src/features/eventTriggers/TriggerSimulation';

// ── Типы пайплайнов (для выпадающего списка) ─────────────────────────

interface PipelineOption {
  id: string;
  name: string;
  is_active: boolean;
}

const PIPELINE_PAGE_SIZE = 50;

function usePipelineOptions(page: number, activeOnly = false) {
  return useQuery({
    queryKey: ['pipelines', 'trigger-options', page, activeOnly],
    queryFn: async ({ signal }) => {
      const { data } = await api.get<{ items: PipelineOption[]; total: number }>('/pipelines', {
        params: { page, per_page: PIPELINE_PAGE_SIZE, ...(activeOnly ? { is_active: true } : {}) },
        signal,
      });
      if (!Array.isArray(data?.items) || !Number.isSafeInteger(data.total) || data.total < data.items.length
        || data.items.some(item => !item || typeof item.id !== 'string'
          || typeof item.name !== 'string' || typeof item.is_active !== 'boolean')) {
        throw new Error('Некорректный каталог пайплайнов');
      }
      return data;
    },
    retry: false,
    staleTime: 30_000,
  });
}

// ── Утилиты ──────────────────────────────────────────────────────────

function timeAgo(dateStr: string | null) {
  if (!dateStr) return '—';
  const at = new Date(dateStr);
  if (!Number.isFinite(at.getTime())) return '—';
  const diff = Date.now() - at.getTime();
  if (diff < 0) return at.toLocaleString('ru-RU');
  if (diff < 60_000) return 'только что';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} мин назад`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} ч назад`;
  return at.toLocaleDateString('ru-RU');
}

// ── Главная страница ─────────────────────────────────────────────────

export default function EventTriggersPage() {
  const access = useCapabilities();
  const canWrite = access.can('pipeline:write');
  const canSimulate = access.can('pipeline:read');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [filterActive, setFilterActive] = useState<string>('__all__');
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EventTrigger | null>(null);

  const params = useMemo(() => ({
    page,
    per_page: 100,
    is_active: filterActive === 'true' ? true : filterActive === 'false' ? false : undefined,
  }), [filterActive, page]);

  const { data, isLoading, isError, isFetching, refetch } = useEventTriggers(params);
  const { data: pipelineCatalog } = usePipelineOptions(1);
  const toggleMut = useToggleEventTrigger();
  const deleteMut = useDeleteEventTrigger();
  const columnCount = canWrite || canSimulate ? 9 : 8;

  const triggers = data?.items ?? [];

  const filtered = useMemo(() => {
    if (!search.trim()) return triggers;
    const q = search.trim().toLowerCase();
    return triggers.filter(t =>
      (t.name || '').toLowerCase().includes(q) ||
      (t.event_type_pattern || '').toLowerCase().includes(q) ||
      (t.description || '').toLowerCase().includes(q),
    );
  }, [triggers, search]);

  const pipelineMap = useMemo(() => {
    const m = new Map<string, string>();
    pipelineCatalog?.items.forEach(p => m.set(p.id, p.name));
    return m;
  }, [pipelineCatalog]);

  return (
    <PageFrame>
      <PageHeading eyebrow="События и диагностика" title="Триггеры событий" description="Запускают пайплайн по шаблону события." actions={<>
        <Button variant="outline" disabled={isFetching} onClick={() => void refetch()}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />Обновить
        </Button>
        {canWrite && <Button onClick={() => setCreateOpen(true)}><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Создать триггер</Button>}
      </>} />
      <PermissionNotice permission="pipeline:write" action="изменять триггеры" />
      <div className="flex flex-wrap items-center gap-3">
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" aria-hidden="true" />
              <Input
                placeholder="Поиск на этой странице…"
                aria-label="Поиск триггеров на текущей странице"
                className="h-9 pl-9"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <Select value={filterActive} onValueChange={(value) => { setFilterActive(value); setPage(1); }}>
              <SelectTrigger aria-label="Активность триггера" className="h-9 w-[140px]">
                <SelectValue placeholder="Все" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">Все</SelectItem>
                <SelectItem value="true">Активные</SelectItem>
                <SelectItem value="false">Неактивные</SelectItem>
              </SelectContent>
            </Select>
      </div>

      {/* ── STATS ──────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Всего по фильтру API" value={isError || isLoading ? '—' : data?.total ?? triggers.length} icon={<Zap className="w-7 h-7 text-primary/30" strokeWidth={1} />} />
          <StatCard label="Активных на странице" value={isError || isLoading ? '—' : triggers.filter(t => t.is_active).length} icon={<Activity className="w-7 h-7 text-success/30" strokeWidth={1} />} />
          <StatCard label="Срабатываний на странице" value={isError || isLoading ? '—' : triggers.reduce((s, t) => s + t.total_triggers, 0)} icon={<GitBranch className="w-7 h-7 text-primary/30" strokeWidth={1} />} />
          <StatCard label="Неактивных со срабатываниями" value={isError || isLoading ? '—' : triggers.filter(t => !t.is_active && t.total_triggers > 0).length} icon={<ShieldAlert className="w-7 h-7 text-muted-foreground/30" strokeWidth={1} />} />
        </div>

      {/* ── ТАБЛИЦА ────────────────────────────────────────────────── */}
        <div className="min-w-0 overflow-x-auto rounded-xl border border-border bg-card shadow-soft">
          <table className="w-full text-left whitespace-nowrap">
            <thead className="border-b border-border bg-muted/50 text-xs font-medium text-muted-foreground">
              <tr>
                <th className="px-4 py-3 w-[50px]">Статус</th>
                <th className="px-4 py-3">Имя</th>
                <th className="px-4 py-3">Паттерн</th>
                <th className="px-4 py-3">Пайплайн</th>
                <th className="px-4 py-3 w-[100px]">Пауза</th>
                <th className="px-4 py-3">Лимит за 60 мин</th>
                <th className="px-4 py-3 w-[100px]">Сработал</th>
                <th className="px-4 py-3 w-[130px]">Последний</th>
                {(canWrite || canSimulate) && <th className="px-4 py-3 w-[120px] text-right">Действия</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-border text-sm text-foreground">
              {isError && <tr><td colSpan={columnCount} className="px-4 py-8 text-center">
                <div role="alert" className="space-y-3">
                  <p>Не удалось загрузить триггеры. Состояние каталога не подтверждено.</p>
                  <Button variant="outline" disabled={isFetching} onClick={() => void refetch()}>Повторить загрузку триггеров</Button>
                </div>
              </td></tr>}
              {isLoading && (
                <tr>
                  <td colSpan={columnCount} className="px-4 py-8 text-center text-muted-foreground">
                    <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2" /> Загрузка...
                  </td>
                </tr>
              )}
              {!isLoading && !isError && filtered.length === 0 && (
                <tr>
                  <td colSpan={columnCount} className="px-4 py-12 text-center text-muted-foreground">
                    <Zap className="w-8 h-8 mx-auto mb-2 opacity-30" />
                    {search ? 'Ничего не найдено на этой странице' : 'В этой выборке нет триггеров'}
                  </td>
                </tr>
              )}
              {!isError && filtered.map((t) => (
                <tr key={t.id} className="hover:bg-muted transition-colors group">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Badge variant={t.is_active ? 'success' : 'secondary'}>{t.is_active ? 'Включён' : 'Отключён'}</Badge>
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
                  <td className="px-4 py-3 text-muted-foreground">
                    {t.max_triggers_per_hour > 0 ? t.max_triggers_per_hour : 'Без лимита'}
                  </td>
                  <td className="px-4 py-3">
                    <span className="font-bold text-foreground">{t.total_triggers}</span>
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">{timeAgo(t.last_triggered_at)}</td>
                  {(canWrite || canSimulate) && <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {canSimulate && <TriggerSimulation trigger={t} canReadEvents={access.can('event:read')} />}
                      {canWrite && <>
                      <Button
                        variant="ghost"
                        size="icon"
                        className={`h-7 w-7 ${t.is_active
                          ? 'text-success hover:text-warning hover:bg-warning/10'
                          : 'text-muted-foreground hover:text-success hover:bg-success/10'
                        }`}
                        title={t.is_active ? 'Деактивировать' : 'Активировать'}
                        aria-label={`${t.is_active ? 'Отключить' : 'Включить'} триггер ${t.name}`}
                        onClick={() => toggleMut.mutate({ id: t.id, active: !t.is_active }, {
                          onSuccess: saved => toast.success(saved.is_active ? 'Триггер включён' : 'Триггер отключён'),
                          onError: error => {
                            toast.error(getApiErrorMessage(error, 'Изменение не подтверждено. Перечитываем список.'));
                            void refetch();
                          },
                        })}
                        disabled={toggleMut.isPending || isFetching}
                      >
                        {t.is_active ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-primary hover:bg-primary/10"
                        title="Редактировать"
                        aria-label={`Редактировать триггер ${t.name}`}
                        onClick={() => setEditTarget(t)}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                        title="Удалить"
                        aria-label={`Удалить триггер ${t.name}`}
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
                      </>}
                    </div>
                  </td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

      <div className="space-y-2">
        <p className="text-xs text-muted-foreground">Текстовый поиск действует на текущую страницу. Для остальных записей используйте страницы; фильтр активности применяется сервером ко всему каталогу.</p>
        {!isLoading && !isError && data && <CatalogPagination page={page} perPage={100} total={data.total} busy={isFetching} label="триггеры" onPageChange={setPage} />}
      </div>

      {/* ── Диалог создания ─────────────────────────────────────── */}
      {canWrite && createOpen && <TriggerFormDialog
        onClose={() => setCreateOpen(false)}
        mode="create"
      />}

      {/* ── Диалог редактирования ───────────────────────────────── */}
      {canWrite && editTarget && (
        <TriggerFormDialog
          onClose={() => setEditTarget(null)}
          mode="edit"
          trigger={editTarget}
        />
      )}
    </PageFrame>
  );
}

// ── Stat Card ────────────────────────────────────────────────────────

function StatCard({ label, value, icon }: { label: string; value: number | string; icon: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-border bg-card p-4">
      <div>
        <div className="mb-1 text-xs text-muted-foreground">{label}</div>
        <div className="text-2xl font-semibold tabular-nums">{value}</div>
      </div>
      {icon}
    </div>
  );
}

// ── Форма создания / редактирования ──────────────────────────────────

interface TriggerFormDialogProps {
  onClose: () => void;
  mode: 'create' | 'edit';
  trigger?: EventTrigger;
}

function TriggerFormDialog({ onClose, mode, trigger }: TriggerFormDialogProps) {
  const createMut = useCreateEventTrigger();
  const updateMut = useUpdateEventTrigger();

  const [name, setName] = useState(trigger?.name ?? '');
  const [description, setDescription] = useState(trigger?.description ?? '');
  const [pattern, setPattern] = useState(trigger?.event_type_pattern ?? '');
  const [selectedPipeline, setSelectedPipeline] = useState<PipelineOption | null>(null);
  const [pipelinePage, setPipelinePage] = useState(1);
  const [cooldown, setCooldown] = useState(String(trigger?.cooldown_seconds ?? 60));
  const [maxPerHour, setMaxPerHour] = useState(String(trigger?.max_triggers_per_hour ?? 100));
  const [paramsJson, setParamsJson] = useState(
    trigger?.input_params_template ? JSON.stringify(trigger.input_params_template, null, 2) : '{}',
  );

  const isSubmitting = createMut.isPending || updateMut.isPending;
  const catalog = usePipelineOptions(pipelinePage, true);
  const pipelines = catalog.isError ? [] : (catalog.data?.items ?? []).filter(p => p.is_active);
  const originalId = trigger?.pipeline_id;
  const validLimits = [cooldown, maxPerHour].every(value => /^\d+$/.test(value) && Number(value) <= 2147483647);
  const validTarget = selectedPipeline ? !catalog.isError && !catalog.isFetching : Boolean(originalId);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const handleSubmit = () => {
    if (isSubmitting || !validTarget || !validLimits) return;
    setSubmitError(null);
    let parsedParams: unknown;
    try {
      parsedParams = JSON.parse(paramsJson);
    } catch {
      setSubmitError('Некорректный JSON в шаблоне параметров.');
      return;
    }
    if (parsedParams === null || typeof parsedParams !== 'object' || Array.isArray(parsedParams)) {
      setSubmitError('Шаблон параметров должен быть JSON-объектом.');
      return;
    }
    if (!name.trim() || !pattern.trim()) {
      setSubmitError('Введите имя и шаблон события.');
      return;
    }
    const fields = {
      name: name.trim(),
      description: description.trim(),
      event_type_pattern: pattern.trim(),
      input_params_template: parsedParams as Record<string, unknown>,
      cooldown_seconds: Number(cooldown),
      max_triggers_per_hour: Number(maxPerHour),
    };

    if (mode === 'create' && selectedPipeline) {
      createMut.mutate(
        {
          ...fields,
          pipeline_id: selectedPipeline.id,
        },
        {
          onSuccess: () => {
            toast.success('Триггер создан');
            onClose();
          },
          onError: err => {
            setSubmitError(getApiErrorMessage(err, 'Создание не подтверждено. Сверьте список перед повтором.'));
          },
        },
      );
    } else if (trigger) {
      updateMut.mutate(
        {
          ...fields,
          id: trigger.id,
          ...(selectedPipeline ? { pipeline_id: selectedPipeline.id } : {}),
        },
        {
          onSuccess: () => {
            toast.success('Триггер обновлён');
            onClose();
          },
          onError: err => {
            setSubmitError(getApiErrorMessage(err, 'Сохранение не подтверждено. Сверьте список перед повтором.'));
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
    <Dialog open onOpenChange={(v) => !v && !isSubmitting && onClose()}>
      <DialogContent layout="workspace" className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg font-semibold">
            <Zap className="w-4 h-4 text-primary" />
            {mode === 'create' ? 'Создать триггер события' : 'Редактировать триггер'}
          </DialogTitle>
          <DialogDescription>
            Триггер автоматически запускает пайплайн при совпадении типа события с шаблоном.
          </DialogDescription>
        </DialogHeader>

        <DialogBody>
          {/* Имя */}
          <div className="space-y-1">
            <Label htmlFor="trigger-name" className="text-sm font-medium">
              Имя *
            </Label>
            <Input id="trigger-name"
              value={name}
              maxLength={255}
              onChange={(e) => setName(e.target.value)}
              placeholder="Бан → Ротация аккаунта"
              className="font-mono text-xs"
            />
          </div>

          {/* Описание */}
          <div className="space-y-1">
            <Label htmlFor="trigger-description" className="text-sm font-medium">
              Описание
            </Label>
            <Input id="trigger-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Авто-ротация аккаунта при бане"
              className="font-mono text-xs"
            />
          </div>

          {/* Паттерн */}
          <div className="space-y-1">
            <Label htmlFor="trigger-pattern" className="text-sm font-medium">
              Шаблон события (glob) *
            </Label>
            <Input id="trigger-pattern"
              value={pattern}
              maxLength={200}
              onChange={(e) => setPattern(e.target.value)}
              placeholder="account.banned"
              className="font-mono text-xs"
            />
            <div className="flex flex-wrap gap-1 mt-1">
              {PATTERN_EXAMPLES.map(p => (
                <Button
                  key={p}
                  type="button"
                  size="sm"
                  variant="outline"
                  className="font-mono text-xs"
                  onClick={() => setPattern(p)}
                >
                  {p}
                </Button>
              ))}
            </div>
          </div>

          {/* Pipeline */}
          <div className="space-y-1">
            <Label htmlFor="trigger-pipeline" className="text-sm font-medium">
              Пайплайн для запуска *
            </Label>
            {originalId && !selectedPipeline && <p className="break-all text-sm text-muted-foreground">Сохранённый пайплайн <span className="font-mono">{originalId}</span></p>}
            {catalog.isPending && <p role="status" className="text-sm text-muted-foreground">Загрузка пайплайнов…</p>}
            {catalog.isError && <div role="alert" className="space-y-2 text-sm">
              <p>Не удалось загрузить каталог пайплайнов.</p>
              <Button type="button" size="sm" variant="outline" disabled={catalog.isFetching} onClick={() => void catalog.refetch()}>Повторить загрузку пайплайнов</Button>
            </div>}
            <select id="trigger-pipeline" value={selectedPipeline?.id ?? ''} disabled={isSubmitting || catalog.isError || catalog.isFetching || !pipelines.length}
              className="min-h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:ring-2 focus-visible:ring-ring"
              onChange={event => setSelectedPipeline(pipelines.find(p => p.id === event.target.value) ?? null)}>
              <option value="">{originalId ? 'Сохранить текущий пайплайн' : 'Выберите активный пайплайн'}</option>
              {selectedPipeline && !pipelines.some(p => p.id === selectedPipeline.id) && <option value={selectedPipeline.id}>{selectedPipeline.name}</option>}
              {pipelines.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            {!catalog.isError && catalog.data?.total === 0 && <p className="text-sm text-muted-foreground">Нет активных пайплайнов.</p>}
            {!catalog.isError && catalog.data && catalog.data.total > PIPELINE_PAGE_SIZE
              && <CatalogPagination page={pipelinePage} perPage={PIPELINE_PAGE_SIZE} total={catalog.data.total}
                busy={catalog.isFetching || Boolean(isSubmitting)} label="пайплайны" onPageChange={setPipelinePage} />}
          </div>

          {/* Cooldown + Rate limit */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="trigger-cooldown" className="text-sm font-medium">
                Пауза между запусками, сек
              </Label>
              <Input id="trigger-cooldown"
                type="number"
                min={0}
                value={cooldown}
                onChange={(e) => setCooldown(e.target.value)}
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="trigger-limit" className="text-sm font-medium">
                Лимит за 60 минут (0 = без лимита)
              </Label>
              <Input id="trigger-limit"
                type="number"
                min={0}
                value={maxPerHour}
                onChange={(e) => setMaxPerHour(e.target.value)}
                className="font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">Движок считает принятые запуски за скользящее окно в 60 минут.</p>
            </div>
          </div>
          {!validLimits && <p role="status" className="text-sm text-destructive">Укажите целые значения от 0 до 2 147 483 647.</p>}

          {/* JSON Template */}
          <div className="space-y-1">
            <Label htmlFor="trigger-params" className="text-sm font-medium">
              Шаблон параметров (JSON)
            </Label>
            <textarea id="trigger-params"
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
        </DialogBody>

        <DialogFooter>
          {submitError && <p role="alert" className="mr-auto text-sm text-destructive">{submitError}</p>}
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Отмена
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting || !validTarget || !validLimits}>
            {isSubmitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
            {mode === 'create' ? 'Создать' : 'Сохранить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
