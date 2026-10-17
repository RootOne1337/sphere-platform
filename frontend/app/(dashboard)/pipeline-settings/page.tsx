'use client';

import { useState, useEffect, useMemo } from 'react';
import {
  Settings2,
  Power,
  PowerOff,
  Activity,
  Users,
  Monitor,
  Ban,
  UserPlus,
  Gamepad2,
  Timer,
  Target,
  Sparkles,
  ShieldAlert,
  Save,
  Loader2,
  RefreshCw,
  Workflow,
  Clock,
} from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  usePipelineSettings,
  useUpdatePipelineSettings,
  useTogglePipeline,
  useOrchestrationStatus,
  type PipelineSettings,
} from '@/lib/hooks/usePipelineSettings';
import { useScripts } from '@/lib/hooks/useScripts';

// ── Типы локального состояния формы ─────────────────────────────────────────

interface FormState {
  max_concurrent_registrations: number;
  registration_script_id: string;
  registration_timeout_seconds: number;
  max_concurrent_farming: number;
  farming_script_id: string;
  farming_session_duration_seconds: number;
  default_target_level: number;
  cooldown_between_sessions_minutes: number;
  nick_generation_enabled: boolean;
  nick_pattern: string;
  ban_detection_enabled: boolean;
  auto_replace_banned: boolean;
  notes: string;
}

function settingsForm(settings: PipelineSettings): FormState {
  return {
    max_concurrent_registrations: settings.max_concurrent_registrations,
    registration_script_id: settings.registration_script_id ?? '',
    registration_timeout_seconds: settings.registration_timeout_seconds,
    max_concurrent_farming: settings.max_concurrent_farming,
    farming_script_id: settings.farming_script_id ?? '',
    farming_session_duration_seconds: settings.farming_session_duration_seconds,
    default_target_level: settings.default_target_level,
    cooldown_between_sessions_minutes: settings.cooldown_between_sessions_minutes,
    nick_generation_enabled: settings.nick_generation_enabled,
    nick_pattern: settings.nick_pattern,
    ban_detection_enabled: settings.ban_detection_enabled,
    auto_replace_banned: settings.auto_replace_banned,
    notes: settings.notes ?? '',
  };
}

// ── Компонент ───────────────────────────────────────────────────────────────

export default function PipelineSettingsPage() {
  const settingsQuery = usePipelineSettings();
  const { data: settings, isLoading, isSuccess, isFetching, isError, refetch } = settingsQuery;
  const { data: status, refetch: refetchStatus } = useOrchestrationStatus();
  const updateMutation = useUpdatePipelineSettings();
  const toggleMutation = useTogglePipeline();
  const { data: scriptsData } = useScripts({ per_page: 200 });

  const scripts = scriptsData?.items ?? [];

  const baseline = useMemo(() => settings ? settingsForm(settings) : null, [settings]);
  const [changes, setChanges] = useState<Partial<FormState>>({});
  const [editBase, setEditBase] = useState<FormState | null>(null);
  const form = baseline ? { ...baseline, ...changes } : null;
  const isDirty = Object.keys(changes).length > 0;
  const writesPending = updateMutation.isPending || toggleMutation.isPending;
  const canWrite = !!baseline && isSuccess && !isFetching && !writesPending;
  const conflicts = baseline && editBase
    ? (Object.keys(changes) as (keyof FormState)[]).filter((key) =>
      baseline[key] !== editBase[key] && baseline[key] !== changes[key])
    : [];

  // Keep user intent separate from refreshed server values. A confirmed equal
  // server value acknowledges that field without discarding unrelated edits.
  useEffect(() => {
    if (!baseline) return;
    setChanges((previous) => {
      const acknowledged = (Object.keys(previous) as (keyof FormState)[])
        .filter((key) => baseline[key] === previous[key]);
      if (!acknowledged.length) return previous;
      const next = { ...previous };
      acknowledged.forEach((key) => { delete next[key]; });
      return next;
    });
  }, [baseline]);

  useEffect(() => { if (!isDirty) setEditBase(null); }, [isDirty]);

  // Обработчик изменения полей
  const updateField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    if (!canWrite || !baseline) return;
    if (!isDirty) setEditBase(baseline);
    setChanges((previous) => {
      const next = { ...previous, [key]: value };
      if (value === baseline[key]) delete next[key];
      return next;
    });
  };

  // Сохранение формы
  const handleSave = () => {
    if (!canWrite || !isDirty || conflicts.length) return;
    const payload: Partial<PipelineSettings> = { ...changes };
    if (payload.registration_script_id === '') payload.registration_script_id = null;
    if (payload.farming_script_id === '') payload.farming_script_id = null;
    if (payload.notes === '') payload.notes = null;
    updateMutation.mutate(payload);
  };

  // Переключатели
  const handleToggle = (feature: 'orchestration' | 'scheduler' | 'registration' | 'farming', enabled: boolean) => {
    if (!canWrite) return;
    toggleMutation.mutate({ feature, enabled });
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  if (!form) {
    return (
      <div className="mx-auto w-full max-w-xl p-6">
        <div role="alert" className="space-y-4 rounded-xl border border-destructive/30 bg-card p-6">
          <h1 className="text-lg font-semibold">Настройки не загружены</h1>
          <p className="text-sm text-muted-foreground">Исходные значения не подтверждены. Изменение настроек и переключателей недоступно.</p>
          <Button onClick={() => void refetch()} disabled={isFetching}>Повторить загрузку настроек</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-card overflow-y-auto custom-scrollbar">
      {/* ── Заголовок ──────────────────────────────────────────────────── */}
      <div className="px-6 py-5 border-b border-border bg-muted shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1 flex items-center gap-2">
              <Settings2 className="w-5 h-5 text-primary" />
              Pipeline Settings
            </h1>
            <p className="text-xs text-muted-foreground font-mono mt-1">
              Персистентные настройки оркестрации. Сохраняются после перезагрузки сервера.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => void Promise.allSettled([refetch(), refetchStatus()])}
              disabled={isFetching || writesPending}
              aria-label="Обновить настройки и состояние"
              className="font-mono text-xs"
            >
              <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
              REFRESH
            </Button>
            <Button
              variant="noc"
              size="sm"
              onClick={handleSave}
              disabled={!canWrite || !isDirty || conflicts.length > 0}
              className="font-mono text-xs"
            >
              {updateMutation.isPending ? (
                <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
              ) : (
                <Save className="w-3.5 h-3.5 mr-1.5" />
              )}
              СОХРАНИТЬ
            </Button>
          </div>
        </div>
      </div>

      {isError && <div role="alert" className="mx-6 mt-4 space-y-2 rounded-lg border border-destructive/30 p-4 text-sm">
        <p>Не удалось обновить настройки. Показан предыдущий снимок и ваши правки; запись заблокирована до успешного чтения.</p>
        <Button variant="outline" onClick={() => void refetch()} disabled={isFetching}>Повторить загрузку настроек</Button>
      </div>}
      {conflicts.length > 0 && <div role="alert" className="mx-6 mt-4 space-y-3 rounded-lg border border-warning/40 p-4 text-sm">
        <p>Редактируемые поля изменились на сервере. Ваши правки сохранены; выберите, какие значения оставить перед записью.</p>
        <p className="break-words font-mono text-xs">{conflicts.join(', ')}</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={!canWrite} onClick={() => setChanges({})}>Принять серверные значения</Button>
          <Button variant="outline" disabled={!canWrite} onClick={() => setEditBase(baseline)}>Оставить мои правки</Button>
        </div>
      </div>}
      <fieldset disabled={!canWrite} className="min-w-0 p-6 space-y-6 max-w-5xl">
        {/* ── Live-статус ────────────────────────────────────────────── */}
        {status && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <StatusCard
              icon={<UserPlus className="w-4 h-4" />}
              label="Активных регистраций"
              value={status.active_registrations}
              color="text-blue-400"
            />
            <StatusCard
              icon={<Gamepad2 className="w-4 h-4" />}
              label="Активных фарм-сессий"
              value={status.active_farming_sessions}
              color="text-green-400"
            />
            <StatusCard
              icon={<Clock className="w-4 h-4" />}
              label="Ожидают регистрации"
              value={status.pending_registrations}
              color="text-yellow-400"
            />
            <StatusCard
              icon={<Monitor className="w-4 h-4" />}
              label="Устройств с сервером"
              value={status.total_devices_with_server}
              color="text-cyan-400"
            />
            <StatusCard
              icon={<Users className="w-4 h-4" />}
              label="Свободных аккаунтов"
              value={status.total_free_accounts}
              color="text-emerald-400"
            />
            <StatusCard
              icon={<Ban className="w-4 h-4" />}
              label="Забанено"
              value={status.total_banned_accounts}
              color="text-red-400"
            />
          </div>
        )}

        {/* ── Главные переключатели ──────────────────────────────────── */}
        <section className="border border-border rounded-sm bg-muted/20 p-5 space-y-4">
          <h2 className="text-sm font-bold font-mono uppercase tracking-wider text-foreground flex items-center gap-2">
            <Power className="w-4 h-4 text-primary" />
            Главные переключатели
          </h2>
          <p className="text-xs text-muted-foreground font-mono">
            Управляй глобальными модулями. Изменения вступают в силу мгновенно и сохраняются в БД.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <ToggleCard
              label="Оркестрация"
              description="Главный переключатель всей автоматизации"
              enabled={settings?.orchestration_enabled ?? false}
              onToggle={(v) => handleToggle('orchestration', v)}
              isPending={toggleMutation.isPending}
              icon={<Workflow className="w-4 h-4" />}
            />
            <ToggleCard
              label="Планировщик задач"
              description="Автоматическая диспетчеризация задач на устройства"
              enabled={settings?.scheduler_enabled ?? false}
              onToggle={(v) => handleToggle('scheduler', v)}
              isPending={toggleMutation.isPending}
              icon={<Activity className="w-4 h-4" />}
            />
            <ToggleCard
              label="Авто-регистрация"
              description="Автоматическое создание игровых аккаунтов"
              enabled={settings?.registration_enabled ?? false}
              onToggle={(v) => handleToggle('registration', v)}
              isPending={toggleMutation.isPending}
              icon={<UserPlus className="w-4 h-4" />}
            />
            <ToggleCard
              label="Авто-фарм"
              description="Автоматическая прокачка аккаунтов до целевого уровня"
              enabled={settings?.farming_enabled ?? false}
              onToggle={(v) => handleToggle('farming', v)}
              isPending={toggleMutation.isPending}
              icon={<Gamepad2 className="w-4 h-4" />}
            />
          </div>
        </section>

        {/* ── Настройки регистрации ──────────────────────────────────── */}
        <section className="border border-border rounded-sm bg-muted/20 p-5 space-y-4">
          <h2 className="text-sm font-bold font-mono uppercase tracking-wider text-foreground flex items-center gap-2">
            <UserPlus className="w-4 h-4 text-blue-400" />
            Регистрация
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label className="text-xs font-mono uppercase text-muted-foreground">
                Скрипт регистрации (DAG)
              </Label>
              <Select
                value={form.registration_script_id || '__none__'}
                onValueChange={(v) => updateField('registration_script_id', v === '__none__' ? '' : v)}
              >
                <SelectTrigger className="h-9 font-mono text-xs">
                  <SelectValue placeholder="Не выбран" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">— Не выбран —</SelectItem>
                  {scripts.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name} ({s.node_count} узлов)
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label className="text-xs font-mono uppercase text-muted-foreground">
                Макс. одновременных
              </Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={form.max_concurrent_registrations}
                onChange={(e) => updateField('max_concurrent_registrations', Number(e.target.value))}
                className="h-9 font-mono text-xs"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-xs font-mono uppercase text-muted-foreground">
                Таймаут (секунды)
              </Label>
              <Input
                type="number"
                min={60}
                max={7200}
                value={form.registration_timeout_seconds}
                onChange={(e) => updateField('registration_timeout_seconds', Number(e.target.value))}
                className="h-9 font-mono text-xs"
              />
            </div>
          </div>
        </section>

        {/* ── Настройки фарма ────────────────────────────────────────── */}
        <section className="border border-border rounded-sm bg-muted/20 p-5 space-y-4">
          <h2 className="text-sm font-bold font-mono uppercase tracking-wider text-foreground flex items-center gap-2">
            <Gamepad2 className="w-4 h-4 text-green-400" />
            Фарм (прокачка)
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label className="text-xs font-mono uppercase text-muted-foreground">
                Скрипт фарма (DAG)
              </Label>
              <Select
                value={form.farming_script_id || '__none__'}
                onValueChange={(v) => updateField('farming_script_id', v === '__none__' ? '' : v)}
              >
                <SelectTrigger className="h-9 font-mono text-xs">
                  <SelectValue placeholder="Не выбран" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">— Не выбран —</SelectItem>
                  {scripts.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name} ({s.node_count} узлов)
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label className="text-xs font-mono uppercase text-muted-foreground">
                Макс. одновременных фарм-сессий
              </Label>
              <Input
                type="number"
                min={1}
                max={500}
                value={form.max_concurrent_farming}
                onChange={(e) => updateField('max_concurrent_farming', Number(e.target.value))}
                className="h-9 font-mono text-xs"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-xs font-mono uppercase text-muted-foreground">
                Длительность сессии (секунды)
              </Label>
              <Input
                type="number"
                min={300}
                max={86400}
                value={form.farming_session_duration_seconds}
                onChange={(e) => updateField('farming_session_duration_seconds', Number(e.target.value))}
                className="h-9 font-mono text-xs"
              />
            </div>
          </div>
        </section>

        {/* ── Уровни и таргеты ───────────────────────────────────────── */}
        <section className="border border-border rounded-sm bg-muted/20 p-5 space-y-4">
          <h2 className="text-sm font-bold font-mono uppercase tracking-wider text-foreground flex items-center gap-2">
            <Target className="w-4 h-4 text-yellow-400" />
            Уровни и цели
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label className="text-xs font-mono uppercase text-muted-foreground">
                Целевой уровень по умолчанию
              </Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={form.default_target_level}
                onChange={(e) => updateField('default_target_level', Number(e.target.value))}
                className="h-9 font-mono text-xs"
              />
            </div>

            <div className="space-y-2">
              <Label className="text-xs font-mono uppercase text-muted-foreground">
                Пауза между сессиями (минуты)
              </Label>
              <Input
                type="number"
                min={0}
                max={1440}
                value={form.cooldown_between_sessions_minutes}
                onChange={(e) => updateField('cooldown_between_sessions_minutes', Number(e.target.value))}
                className="h-9 font-mono text-xs"
              />
            </div>
          </div>
        </section>

        {/* ── Генерация ников ────────────────────────────────────────── */}
        <section className="border border-border rounded-sm bg-muted/20 p-5 space-y-4">
          <h2 className="text-sm font-bold font-mono uppercase tracking-wider text-foreground flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-purple-400" />
            Генерация никнеймов
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex items-center justify-between border border-border rounded-sm p-3 bg-card">
              <div>
                <p className="text-xs font-mono font-bold text-foreground">Авто-генерация</p>
                <p className="text-[10px] text-muted-foreground font-mono">
                  Автоматически генерировать имена для новых аккаунтов
                </p>
              </div>
              <Switch
                aria-label="Авто-генерация"
                checked={form.nick_generation_enabled}
                onCheckedChange={(v) => updateField('nick_generation_enabled', v)}
              />
            </div>

            <div className="space-y-2">
              <Label className="text-xs font-mono uppercase text-muted-foreground">
                Шаблон никнейма
              </Label>
              <Input
                value={form.nick_pattern}
                onChange={(e) => updateField('nick_pattern', e.target.value)}
                placeholder="{first_name}_{last_name}"
                className="h-9 font-mono text-xs"
              />
              <p className="text-[10px] text-muted-foreground font-mono">
                Переменные: {'{first_name}'}, {'{last_name}'}, {'{digits}'}
              </p>
            </div>
          </div>
        </section>

        {/* ── Мониторинг и защита ────────────────────────────────────── */}
        <section className="border border-border rounded-sm bg-muted/20 p-5 space-y-4">
          <h2 className="text-sm font-bold font-mono uppercase tracking-wider text-foreground flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 text-red-400" />
            Мониторинг банов
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex items-center justify-between border border-border rounded-sm p-3 bg-card">
              <div>
                <p className="text-xs font-mono font-bold text-foreground">Обнаружение банов</p>
                <p className="text-[10px] text-muted-foreground font-mono">
                  Автоматическая детекция забаненных аккаунтов
                </p>
              </div>
              <Switch
                aria-label="Обнаружение банов"
                checked={form.ban_detection_enabled}
                onCheckedChange={(v) => updateField('ban_detection_enabled', v)}
              />
            </div>

            <div className="flex items-center justify-between border border-border rounded-sm p-3 bg-card">
              <div>
                <p className="text-xs font-mono font-bold text-foreground">Авто-замена</p>
                <p className="text-[10px] text-muted-foreground font-mono">
                  Создавать новые аккаунты взамен забаненных
                </p>
              </div>
              <Switch
                aria-label="Авто-замена"
                checked={form.auto_replace_banned}
                onCheckedChange={(v) => updateField('auto_replace_banned', v)}
              />
            </div>
          </div>
        </section>

        {/* ── Заметки ────────────────────────────────────────────────── */}
        <section className="border border-border rounded-sm bg-muted/20 p-5 space-y-4">
          <h2 className="text-sm font-bold font-mono uppercase tracking-wider text-foreground flex items-center gap-2">
            <Timer className="w-4 h-4 text-muted-foreground" />
            Заметки
          </h2>
          <textarea
            aria-label="Заметки"
            value={form.notes}
            onChange={(e) => updateField('notes', e.target.value)}
            placeholder="Заметки администратора (необязательно)..."
            rows={3}
            className="w-full rounded-sm border border-border bg-background p-3 text-xs font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary resize-y"
          />
        </section>

        {/* Нижняя кнопка сохранения */}
        {isDirty && (
          <div className="flex justify-end pb-4">
            <Button
              variant="noc"
              size="sm"
              onClick={handleSave}
              disabled={!canWrite || conflicts.length > 0}
              className="font-mono text-xs"
            >
              {updateMutation.isPending ? (
                <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
              ) : (
                <Save className="w-3.5 h-3.5 mr-1.5" />
              )}
              СОХРАНИТЬ ИЗМЕНЕНИЯ
            </Button>
          </div>
        )}
      </fieldset>
    </div>
  );
}

// ── Sub-компоненты ──────────────────────────────────────────────────────────

function StatusCard({
  icon,
  label,
  value,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="border border-border rounded-sm bg-card p-3 space-y-1">
      <div className={`flex items-center gap-1.5 ${color}`}>
        {icon}
        <span className="text-lg font-bold font-mono">{value}</span>
      </div>
      <p className="text-[10px] text-muted-foreground font-mono uppercase leading-tight">
        {label}
      </p>
    </div>
  );
}

function ToggleCard({
  label,
  description,
  enabled,
  onToggle,
  isPending,
  icon,
}: {
  label: string;
  description: string;
  enabled: boolean;
  onToggle: (v: boolean) => void;
  isPending: boolean;
  icon: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between border border-border rounded-sm p-4 bg-card">
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 ${enabled ? 'text-primary' : 'text-muted-foreground'}`}>
          {icon}
        </div>
        <div>
          <span className="text-xs font-mono font-bold text-foreground flex items-center gap-2">
            {label}
            <Badge
              className={`text-[9px] px-1.5 py-0 font-mono ${
                enabled
                  ? 'bg-green-500/20 text-green-400 border-green-500/30'
                  : 'bg-muted text-muted-foreground border-border'
              }`}
            >
              {enabled ? 'ON' : 'OFF'}
            </Badge>
          </span>
          <span className="block text-[10px] text-muted-foreground font-mono mt-0.5">{description}</span>
        </div>
      </div>
      <Switch
        aria-label={label}
        checked={enabled}
        onCheckedChange={onToggle}
        disabled={isPending}
      />
    </div>
  );
}
