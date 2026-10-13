import { render, screen } from '@testing-library/react';
import { NativeInputDiagnostic, type NativeInputTelemetry } from '@/components/sphere/NativeInputDiagnostic';

const telemetry: NativeInputTelemetry = {
  schema_version: 1, scope: 'agent_process', state: 'cleanup_unknown', last_failure: 'cleanup_unknown',
  last_failure_age_ms: 120, open_attempts_total: 3, open_rejections_total: 2, startups_total: 1,
  startup_failures_total: 0, input_failures_total: 0, releases_total: 0, unknown_releases_total: 1,
};

test('an older APK is unreported rather than healthy or zero', () => {
  render(<NativeInputDiagnostic />);
  expect(screen.getByText('Диагностика ввода APK не передана.')).toBeInTheDocument();
  expect(screen.queryByText(/Свободен/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Запросы запуска/)).not.toBeInTheDocument();
});

test('unknown release has a readable cause and process scope', () => {
  render(<NativeInputDiagnostic telemetry={telemetry} />);
  expect(screen.getByText(/Ввод Android: Освобождение не подтверждено/)).toBeInTheDocument();
  expect(screen.getByText(/Android не подтвердил освобождение предыдущего ввода/)).toBeInTheDocument();
  expect(screen.getByText(/Неподтверждённые освобождения: 1/)).toBeInTheDocument();
  expect(screen.getByText(/Счётчики за время работы процесса APK/)).toBeInTheDocument();
});

test('a previous busy cause is not presented as the current state', () => {
  render(<NativeInputDiagnostic telemetry={{ ...telemetry, state: 'ready', last_failure: 'active_owner', last_failure_age_ms: 0 }} />);
  expect(screen.getByText(/Ввод Android: Готов/)).toBeInTheDocument();
  expect(screen.getByText(/Последний сбой: Ввод занят другим владельцем · 0 мс/)).toBeInTheDocument();
});

test('a historical startup problem remains separate from a ready current adapter', () => {
  render(<NativeInputDiagnostic telemetry={{ ...telemetry, state: 'ready',
    last_startup_detail: 'root_geometry', last_startup_detail_age_ms: 300 }} />);
  expect(screen.getByText(/Ввод Android: Готов/)).toBeInTheDocument();
  expect(screen.getByText(/Последний сбой запуска: Размер или поворот экрана изменился при запуске · 300 мс/)).toBeInTheDocument();
});

test('a confirmed current adapter retains its separately dated release cause', () => {
  render(<NativeInputDiagnostic telemetry={{ ...telemetry, state: 'ready',
    last_release_reason: 'viewer_closed', last_release_age_ms: 260706,
    last_failure: 'receipt_unavailable', last_failure_age_ms: 32422753 }} />);
  expect(screen.getByText('Ввод Android: Готов')).toBeInTheDocument();
  expect(screen.getByText(/Последнее завершение: Клиент закрыл управление · 4 мин 20 с назад в срезе/)).toBeInTheDocument();
  expect(screen.getByText(/Последний сбой: Не удалось отправить подтверждение Android · 9 ч назад в срезе/)).toBeInTheDocument();
});

test('release cause does not imply successful cleanup', () => {
  render(<NativeInputDiagnostic telemetry={{ ...telemetry,
    last_release_reason: 'cleanup_unknown', last_release_age_ms: 0 }} />);
  expect(screen.getByText(/Последнее завершение: Освобождение ввода не подтверждено · 0 мс назад в срезе/)).toBeInTheDocument();
  expect(screen.getByText('Неподтверждённые освобождения: 1')).toBeInTheDocument();
});

test('older agents do not get an invented release cause', () => {
  render(<NativeInputDiagnostic telemetry={telemetry} />);
  expect(screen.queryByText(/Последнее завершение/)).not.toBeInTheDocument();
});

test.each(['authorization_expired', 'viewer_heartbeat_expired', 'native_failure'] as const)(
  'shows a recognised native release cause: %s', reason => {
    render(<NativeInputDiagnostic telemetry={{ ...telemetry, last_release_reason: reason, last_release_age_ms: 86400000 }} />);
    expect(screen.getByText(/Последнее завершение:/)).not.toHaveTextContent('Причина не распознана');
    expect(screen.getByText(/не менее 24 ч назад в срезе/)).toBeInTheDocument();
  },
);

test.each(['future_reason', '__proto__', 'constructor'])('unknown cause %s stays readable', reason => {
  render(<NativeInputDiagnostic telemetry={{ ...telemetry,
    last_release_reason: reason as NativeInputTelemetry['last_release_reason'], last_release_age_ms: 1000 }} />);
  expect(screen.getByText(/Последнее завершение: Причина не распознана · 1 с назад в срезе/)).toBeInTheDocument();
});
