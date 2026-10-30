import { getApiErrorMessage } from '@/lib/apiError';

const stages: Record<string, string> = {
  geometry_before: 'Геометрия экрана до чтения', dump: 'Создание дампа UI Automator',
  read_xml: 'Чтение файла дерева', geometry_after: 'Геометрия экрана после чтения',
  validate_geometry: 'Проверка геометрии', validate_tree: 'Проверка структуры дерева',
};
const reasons: Record<string, string> = {
  native_exit_nonzero: 'Android завершил команду с ненулевым кодом.',
  native_input_busy: 'Android занят другим управлением. Дождитесь его завершения.',
  native_input_outcome_unknown: 'Результат предыдущего управления Android не подтверждён.',
  native_command_failed: 'Android не выполнил команду чтения. Причина не подтверждена.',
  transport_unavailable: 'Канал команд устройства недоступен.',
  command_deadline_exceeded: 'Истёк срок ожидания ответа команды Android.',
  snapshot_deadline_exceeded: 'Истёк срок получения полного дерева Android.',
  invalid_device_receipt: 'Ответ устройства не содержит полного результата чтения.',
  inspection_internal_error: 'Сервер не завершил чтение дерева. Проверьте логи по идентификатору снимка.',
  display_geometry_changed: 'Во время чтения изменилась геометрия экрана. Получите новый снимок дерева.',
  display_geometry_unavailable: 'Android не сообщил геометрию экрана.',
  display_geometry_invalid: 'Android сообщил некорректную геометрию экрана.',
  ui_dump_invalid_text: 'Дамп Android содержит некорректный текст.',
  ui_dump_byte_budget_exceeded: 'Дамп превысил допустимый размер 128 KiB.',
  ui_dump_entities_forbidden: 'Дамп содержит запрещённые XML-сущности.',
  ui_dump_structure_invalid: 'Структура дампа Android некорректна.',
  ui_dump_rotation_invalid: 'Поворот экрана в дампе некорректен.',
  ui_dump_root_invalid: 'Корневой элемент дампа Android некорректен.',
  ui_dump_structure_budget_exceeded: 'Дерево превысило допустимую глубину или число элементов.',
  ui_dump_attribute_budget_exceeded: 'Атрибуты дерева превысили допустимый размер.',
  ui_dump_incomplete_or_invalid: 'Android вернул неполный или некорректный XML-дамп.',
};
export type UiInspectionError = {
  message: string;
  diagnostic?: { snapshotId: string; stage: string; stageLabel: string; reason: string; nativeExitCode?: number; cleanupUnconfirmed: boolean };
};

export function uiInspectionError(error: unknown): UiInspectionError {
  const fallback = { message: getApiErrorMessage(error, error instanceof Error ? error.message : 'Не удалось прочитать дерево Android.') };
  if (!error || typeof error !== 'object' || !('response' in error)) return fallback;
  const response = error.response;
  if (!response || typeof response !== 'object' || !('headers' in response)) return fallback;
  const headers = response.headers;
  if (!headers || typeof headers !== 'object') return fallback;
  const read = (name: string) => (headers as Record<string, unknown>)[name];
  const stage = read('x-sphere-ui-stage'), reason = read('x-sphere-ui-reason'), snapshotId = read('x-sphere-ui-snapshot');
  // These are protocol enums, not a channel for native stderr, commands or XML.
  if (typeof stage !== 'string' || !Object.hasOwn(stages, stage)
      || typeof reason !== 'string' || !Object.hasOwn(reasons, reason)
      || typeof snapshotId !== 'string' || !/^[a-f0-9]{32}$/.test(snapshotId)) return fallback;
  const rawExit = read('x-sphere-ui-native-exit-code');
  const nativeExitCode = reason === 'native_exit_nonzero' && typeof rawExit === 'string'
    && /^[1-9][0-9]{0,2}$/.test(rawExit) && Number(rawExit) <= 255 ? Number(rawExit) : undefined;
  return {
    message: nativeExitCode === undefined ? reasons[reason] : `Android завершил команду с кодом ${nativeExitCode}. Причина отказа требует проверки логов.`,
    diagnostic: { snapshotId, stage, stageLabel: stages[stage], reason, nativeExitCode,
      cleanupUnconfirmed: read('x-sphere-ui-cleanup') === 'unconfirmed' },
  };
}
