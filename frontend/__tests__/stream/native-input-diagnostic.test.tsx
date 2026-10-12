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
