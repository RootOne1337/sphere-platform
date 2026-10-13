export interface NativeInputTelemetry {
  schema_version: 1;
  scope: 'agent_process';
  state: 'disabled' | 'idle' | 'opening' | 'ready' | 'retiring' | 'cleanup_unknown';
  last_failure?: keyof typeof failureLabels | null;
  last_failure_age_ms?: number | null;
  last_startup_detail?: keyof typeof startupLabels | null;
  last_startup_detail_age_ms?: number | null;
  last_release_reason?: keyof typeof releaseLabels | null;
  last_release_age_ms?: number | null;
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

const startupLabels = {
  root_required: 'Привилегированный адаптер недоступен',
  root_geometry: 'Размер или поворот экрана изменился при запуске',
  root_adapter_unavailable: 'Системный адаптер ввода недоступен',
  root_configuration: 'Параметры адаптера отклонены',
  root_handshake: 'Готовность адаптера не подтверждена',
  root_process_exited: 'Процесс адаптера завершился до готовности',
  root_ready_timeout: 'Адаптер не подтвердил готовность в срок',
  root_handoff_unknown: 'Завершение предыдущего адаптера не подтверждено',
};

const releaseLabels = {
  owner_retired: 'Причина завершения не уточнена',
  viewer_closed: 'Клиент закрыл управление',
  viewer_heartbeat_expired: 'Задержался heartbeat клиента',
  pending_input_expired: 'Действие не доставлено в допустимый срок',
  invalid_input: 'Некорректное сообщение ввода',
  queue_overflow: 'Очередь ввода переполнена',
  clock_regression: 'Нарушен порядок монотонных часов агента',
  authorization_expired: 'Истёк допуск управления',
  scope_inactive: 'Служба агента завершает работу',
  transport_changed: 'Изменилось подключение агента',
  capture_changed: 'Изменился захват экрана',
  direct_channel_unavailable: 'Прямой канал управления недоступен',
  receipt_unavailable: 'Не удалось отправить подтверждение Android',
  native_failure: 'Ошибка нативного ввода',
  startup_refused: 'Android отказал в запуске ввода',
  cleanup_unknown: 'Освобождение ввода не подтверждено',
};

function label(labels: Record<string, string>, key: string, fallback = 'Причина не распознана') {
  return Object.prototype.hasOwnProperty.call(labels, key) ? labels[key] ?? fallback : fallback;
}

/** Ages belong to the APK snapshot. Its capped 24-hour value is a lower bound. */
function snapshotAge(ms?: number | null): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return '';
  const age = Math.floor(ms);
  let text: string;
  if (age >= 86_400_000) text = 'не менее 24 ч';
  else if (age >= 3_600_000) text = `${Math.floor(age / 3_600_000)} ч`;
  else if (age >= 60_000) {
    const seconds = Math.floor(age % 60_000 / 1000);
    text = `${Math.floor(age / 60_000)} мин${seconds ? ` ${seconds} с` : ''}`;
  } else if (age >= 1000) text = `${Math.floor(age / 1000)} с`;
  else text = `${age} мс`;
  return ` · ${text} назад в срезе`;
}

/** Shown only inside diagnostics. A process counter is not a per-viewer success rate. */
export function NativeInputDiagnostic({ telemetry }: { telemetry?: NativeInputTelemetry | null }) {
  if (!telemetry) return <div className="col-span-2 mt-2">Диагностика ввода APK не передана.</div>;
  const reason = telemetry.last_failure;
  return (
    <div className="col-span-2 mt-2 min-w-0 space-y-1 break-words rounded-md border border-border p-2" data-native-input-diagnostic>
      <div className="font-medium">Ввод Android: {label(stateLabels, telemetry.state, 'Нет измерения')}</div>
      {reason ? (
        <div>Последний сбой: {label(failureLabels, reason)}
          {snapshotAge(telemetry.last_failure_age_ms)}
        </div>
      ) : <div>Сбои ввода в процессе агента не зафиксированы.</div>}
      {telemetry.last_startup_detail && <div>
        Последний сбой запуска: {label(startupLabels, telemetry.last_startup_detail)}
        {snapshotAge(telemetry.last_startup_detail_age_ms)}.
      </div>}
      {telemetry.last_release_reason && <div>
        Последнее завершение: {label(releaseLabels, telemetry.last_release_reason)}
        {snapshotAge(telemetry.last_release_age_ms)}
      </div>}
      <div className="grid grid-cols-1 gap-x-3 break-words sm:grid-cols-2">
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
