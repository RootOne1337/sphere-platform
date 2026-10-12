export interface NativeInputTelemetry {
  schema_version: 1;
  scope: 'agent_process';
  state: 'disabled' | 'idle' | 'opening' | 'ready' | 'retiring' | 'cleanup_unknown';
  last_failure?: keyof typeof failureLabels | null;
  last_failure_age_ms?: number | null;
  open_attempts_total: number;
  open_rejections_total: number;
  startups_total: number;
  startup_failures_total: number;
  input_failures_total: number;
  releases_total: number;
  unknown_releases_total: number;
}

const stateLabels = {
  disabled: 'Выключен', idle: 'Свободен', opening: 'Запуск', ready: 'Готов',
  retiring: 'Завершение', cleanup_unknown: 'Освобождение не подтверждено',
};

const failureLabels = {
  active_owner: 'Ввод занят другим владельцем',
  retiring_owner: 'Предыдущее управление завершается',
  capture_unavailable: 'Нет активного захвата',
  capture_changed: 'Изменился захват экрана',
  direct_channel_unavailable: 'Прямой канал управления недоступен',
  authorization_expired: 'Истёк допуск управления',
  transport_changed: 'Изменилось подключение агента',
  supervisor_busy: 'Обработчик предыдущего ввода ещё работает',
  cleanup_unknown: 'Android не подтвердил освобождение предыдущего ввода',
  native_startup_failed: 'Не удалось запустить ввод Android',
  native_input_failed: 'Android не подтвердил действие',
  input_not_ready: 'Действие пришло до готовности ввода',
  input_rejected: 'Действие отклонено Android',
  receipt_unavailable: 'Не удалось отправить подтверждение Android',
  scope_inactive: 'Служба агента завершает работу',
};

/** Shown only inside diagnostics. A process counter is not a per-viewer success rate. */
export function NativeInputDiagnostic({ telemetry }: { telemetry?: NativeInputTelemetry | null }) {
  if (!telemetry) return <div className="col-span-2 mt-2">Диагностика ввода APK не передана.</div>;
  const reason = telemetry.last_failure;
  return (
    <div className="col-span-2 mt-2 space-y-1 rounded-md border border-border p-2" data-native-input-diagnostic>
      <div className="font-medium">Ввод Android: {stateLabels[telemetry.state] ?? 'Нет измерения'}</div>
      {reason ? (
        <div>Последний сбой: {failureLabels[reason] ?? 'Причина не распознана'}
          {telemetry.last_failure_age_ms != null && ` · ${telemetry.last_failure_age_ms} мс назад в срезе`}
        </div>
      ) : <div>Сбои ввода в процессе агента не зафиксированы.</div>}
      <div className="grid grid-cols-2 gap-x-3 break-words">
        <span>Запросы запуска: {telemetry.open_attempts_total}</span>
        <span>Отказы до запуска: {telemetry.open_rejections_total}</span>
        <span>Готовые запуски: {telemetry.startups_total}</span>
        <span>Сбои запуска: {telemetry.startup_failures_total}</span>
        <span>Сбои действий: {telemetry.input_failures_total}</span>
        <span>Освобождения: {telemetry.releases_total}</span>
        <span>Неподтверждённые освобождения: {telemetry.unknown_releases_total}</span>
      </div>
      <div className="text-muted-foreground">Счётчики за время работы процесса APK. Последний сбой может относиться к предыдущему сеансу; состояние выше относится к этому срезу.</div>
    </div>
  );
}
