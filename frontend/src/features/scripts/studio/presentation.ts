import type { DagNode } from '@/lib/dag/export';
import { ACTION_LABELS } from '@/lib/dag/studio';

export const ACTION_GROUPS = [
  { name: 'Управление экраном', types: ['tap', 'swipe', 'long_press', 'double_tap', 'scroll', 'key_event', 'type_text', 'input_clear'] },
  { name: 'Элементы и проверки', types: ['find_element', 'tap_element', 'find_first_element', 'tap_first_visible', 'get_element_text', 'wait_for_element_gone', 'scroll_to', 'assert'] },
  { name: 'Логика и данные', types: ['sleep', 'condition', 'set_variable', 'get_variable', 'increment_variable', 'lua', 'start', 'end'] },
  { name: 'Приложения и система', types: ['launch_app', 'stop_app', 'clear_app_data', 'screenshot', 'shell', 'http_request', 'open_url', 'get_device_info'] },
] as const;
export function actionLabel(type: string) { return ACTION_LABELS[type as keyof typeof ACTION_LABELS] ?? type; }
export function actionSummary(action: DagNode['action']): string {
  const type = action.type;
  if (type === 'start') return 'Точка входа сценария';
  if (type === 'end') return 'Завершить выполнение';
  if (type === 'sleep') return `${action.ms ?? '—'} мс`;
  if (['tap', 'long_press', 'double_tap'].includes(type)) return `X ${action.x ?? '—'} · Y ${action.y ?? '—'}`;
  if (type === 'swipe') return `${action.x1}, ${action.y1} → ${action.x2}, ${action.y2}`;
  if (typeof action.selector === 'string') return action.selector;
  if (type === 'type_text') return 'Текст и очистка поля'; // Never expose private input on the canvas.
  if (type === 'condition' || type === 'assert') return String(action.check ?? 'Lua-проверка');
  if (typeof action.package === 'string') return action.package || 'Укажите пакет Android';
  if (typeof action.url === 'string') return `${action.method ?? ''} ${action.url}`.trim();
  if (typeof action.key === 'string') return `Переменная · ${action.key}`;
  if (type === 'shell' || type === 'lua') return 'Код на устройстве';
  return type === 'key_event' ? `Android keycode ${action.keycode}` : actionLabel(type);
}

export const FIELD_LABELS: Record<string, string> = {
  retry: 'Повторы', node_id: 'Узел с HTTP-ответом',
  x: 'Координата X', y: 'Координата Y', x1: 'Начало X', y1: 'Начало Y', x2: 'Конец X', y2: 'Конец Y',
  ms: 'Ожидание, мс', duration_ms: 'Длительность, мс', timeout_ms: 'Ожидание ответа, мс', delay_ms: 'После запуска, мс',
  keycode: 'Код клавиши Android', selector: 'Селектор элемента', strategy: 'Стратегия поиска', text: 'Текст',
  clear_first: 'Сначала очистить поле', save_to: 'Сохранить в переменную', attribute: 'Атрибут элемента',
  direction: 'Направление', percent: 'Доля экрана', max_scrolls: 'Максимум прокруток', package: 'Пакет приложения',
  check: 'Тип проверки', params: 'Параметры проверки', candidates: 'Кандидаты поиска', key: 'Имя переменной',
  value: 'Значение', step: 'Изменение счётчика', command: 'Shell-команда', code: 'Lua-код', url: 'URL',
  method: 'Метод HTTP', headers: 'Заголовки HTTP', body: 'Тело запроса', message: 'Сообщение при ошибке',
};
