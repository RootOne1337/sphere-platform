import { ACTION_TYPES, importDag, validateDag, type DagExport } from './export';
import type { Node, Edge } from '@xyflow/react';

export const SOURCE_LIMIT = 512 * 1024;
export const HISTORY_LIMIT = 20;
export const HISTORY_BYTES = 2 * 1024 * 1024;
export const DRAFT_TTL = 7 * 24 * 60 * 60 * 1000;
export type StudioDocument = { name: string; source: string };
export const byteLength = (text: string) => new TextEncoder().encode(text).byteLength;
export function boundedSource(source: string): string {
  if (byteLength(source) > SOURCE_LIMIT) throw new Error('Исходник превышает 512 KiB. Текст не заменён.');
  return source;
}
export function parseSource(source: string): DagExport {
  boundedSource(source);
  let value: unknown;
  try { value = JSON.parse(source); } catch { throw new Error('Некорректный JSON. Исправьте исходник; прежний граф не будет сохранён вместо него.'); }
  const errors = validateDag(value);
  if (errors.length) throw new Error(errors.slice(0, 20).join('\n'));
  return value as DagExport;
}
export const initialDag: DagExport = { version: '1.0', entry_node: 'start-1', timeout_ms: 1800000, nodes: [
  { id: 'start-1', action: { type: 'start' }, on_success: 'end-1', on_failure: null, retry: 0, timeout_ms: 30000 },
  { id: 'end-1', action: { type: 'end' }, on_success: null, on_failure: null, retry: 0, timeout_ms: 30000 },
] };
export const formatDag = (dag: DagExport) => JSON.stringify(dag, null, 2);
export function pushHistory(history: StudioDocument[], document: StudioDocument): StudioDocument[] {
  const next = [...history, document].slice(-HISTORY_LIMIT);
  let bytes = next.reduce((sum, item) => sum + byteLength(JSON.stringify(item)), 0);
  while (bytes > HISTORY_BYTES && next.length) bytes -= byteLength(JSON.stringify(next.shift()));
  return next;
}
export function draftKey(org: string, user: string): string {
  return `sphere-studio-draft-v1:${encodeURIComponent(org)}:${encodeURIComponent(user)}`;
}
export function readDraft(raw: string | null, resource: string, now = Date.now()): StudioDocument | null {
  if (!raw) return null;
  if (byteLength(raw) > SOURCE_LIMIT + 16384) throw new Error('Локальный черновик превышает лимит.');
  let value: unknown;
  try { value = JSON.parse(raw); } catch { throw new Error('Локальный черновик повреждён.'); }
  const draft = value as Record<string, unknown> | null;
  if (!draft || draft.version !== 1 || typeof draft.savedAt !== 'number' || !Number.isFinite(draft.savedAt)
    || now - draft.savedAt > DRAFT_TTL || draft.savedAt > now + 60000 || draft.resource !== resource) return null;
  if (typeof draft.name !== 'string' || draft.name.length > 255 || typeof draft.source !== 'string') throw new Error('Неверный формат локального черновика.');
  return { name: draft.name, source: boundedSource(draft.source) };
}
export function writeDraft(document: StudioDocument, resource: string, now = Date.now()): string {
  boundedSource(document.source);
  if (!document.name.trim() || document.name.length > 255) throw new Error('Название черновика: 1–255 символов.');
  const raw = JSON.stringify({ version: 1, resource, savedAt: now, ...document });
  if (byteLength(raw) > SOURCE_LIMIT + 16384) throw new Error('Локальный черновик с учётом JSON-кодирования превышает лимит. Экспортируйте файл.');
  return raw;
}

type ActionType = typeof ACTION_TYPES[number];
export const ACTION_LABELS: Record<ActionType, string> = {
  start: 'Начало', end: 'Завершение', tap: 'Нажатие', swipe: 'Свайп', type_text: 'Ввод текста', sleep: 'Ожидание',
  find_element: 'Найти элемент', key_event: 'Клавиша Android', lua: 'Lua', screenshot: 'Снимок экрана', condition: 'Условие',
  launch_app: 'Открыть приложение', stop_app: 'Остановить приложение', clear_app_data: 'Очистить данные приложения',
  find_first_element: 'Первый найденный элемент', tap_first_visible: 'Нажать первый видимый', tap_element: 'Нажать по селектору',
  get_element_text: 'Текст элемента', wait_for_element_gone: 'Дождаться исчезновения', scroll_to: 'Прокрутить до элемента',
  long_press: 'Долгое нажатие', double_tap: 'Двойное нажатие', scroll: 'Прокрутка', set_variable: 'Задать переменную',
  get_variable: 'Прочитать переменную', increment_variable: 'Изменить счётчик', shell: 'Shell-команда', input_clear: 'Очистить поле',
  http_request: 'HTTP-запрос с Android', open_url: 'Открыть URL', get_device_info: 'Информация об устройстве', assert: 'Проверка результата',
};
const SELECTOR = { selector: '//*[@text="Настройки"]', strategy: 'xpath', timeout_ms: 5000 };
const templates: Partial<Record<ActionType, Record<string, unknown>>> = {
  tap: { x: 100, y: 100 }, swipe: { x1: 100, y1: 400, x2: 100, y2: 100, duration_ms: 300 },
  type_text: { text: '', clear_first: false }, sleep: { ms: 1000 }, key_event: { keycode: 4 }, lua: { code: 'return true' },
  condition: { check: 'battery_above', params: { level: 20 } }, find_element: { ...SELECTOR, save_to: 'element' },
  tap_element: SELECTOR, get_element_text: { ...SELECTOR, attribute: 'text', save_to: 'text' }, wait_for_element_gone: SELECTOR,
  scroll_to: { ...SELECTOR, direction: 'down', max_scrolls: 10 },
  find_first_element: { candidates: [{ ...SELECTOR }], timeout_ms: 5000 },
  tap_first_visible: { candidates: [{ ...SELECTOR }], timeout_ms: 5000 },
  launch_app: { package: 'com.android.settings', delay_ms: 1500 }, stop_app: { package: 'com.android.settings' },
  clear_app_data: { package: '' }, long_press: { x: 100, y: 100, duration_ms: 800 }, double_tap: { x: 100, y: 100 },
  scroll: { direction: 'down', percent: 0.45, duration_ms: 350 }, set_variable: { key: 'value', value: '' },
  get_variable: { key: 'value' }, increment_variable: { key: 'counter', step: 1 }, shell: { command: 'getprop ro.build.version.release', save_to: 'output' },
  http_request: { url: 'https://example.com', method: 'GET', timeout_ms: 15000, save_to: 'response' },
  open_url: { url: 'https://example.com' }, get_device_info: { save_to: 'device' },
  assert: { check: 'element_exists', params: SELECTOR, message: 'Элемент не найден' },
};
export function defaultAction(type: ActionType) {
  return JSON.parse(JSON.stringify({ type, ...templates[type] })) as DagExport['nodes'][number]['action'];
}
/** Bounded breadth-first layout. Cycles remain explicit back edges and never
 * recurse. Canvas placement is not part of the executable/hash contract. */
export function arrangeNodes(nodes: Node[], edges: Edge[], entry: string): Node[] {
  const adjacency = new Map<string, string[]>();
  for (const edge of edges) adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
  const levels = new Map<string, number>([[entry, 0]]);
  const queue = [entry];
  for (let index = 0; index < queue.length; index++) {
    for (const target of adjacency.get(queue[index]) ?? []) if (!levels.has(target)) {
      levels.set(target, (levels.get(queue[index]) ?? 0) + 1); queue.push(target);
    }
  }
  const columns = new Map<number, number>();
  return nodes.map(node => {
    const level = levels.get(node.id) ?? levels.size;
    const column = columns.get(level) ?? 0; columns.set(level, column + 1);
    return { ...node, position: { x: level * 346, y: column * 210 } };
  });
}
/** Insert after the selected linear step, or immediately before an existing end.
 * Branch insertion requires choosing a linear step, never silently rewires a condition.
 */
export function insertAction(dag: DagExport, type: ActionType, id: string, selected?: string): DagExport {
  if (dag.nodes.length >= 500) throw new Error('Лимит графа: 500 шагов.');
  if (dag.nodes.some(node => node.id === id)) throw new Error('ID шага уже существует.');
  const next = JSON.parse(JSON.stringify(dag)) as DagExport;
  let parent = next.nodes.find(node => node.id === selected && !['condition', 'end'].includes(node.action.type));
  parent ??= next.nodes.find(node => node.on_success && next.nodes.some(end => end.id === node.on_success && end.action.type === 'end'));
  if (!parent) throw new Error('Выберите линейный шаг для вставки. Ветви условия редактируются в параметрах или JSON.');
  const target = parent.on_success;
  if (type === 'condition' && !target) throw new Error('Условию нужны две ветви: выберите шаг с последующим переходом.');
  const action = defaultAction(type);
  if (type === 'condition') { action.on_true = target; action.on_false = target; }
  next.nodes.push({ id, action, on_success: type === 'condition' ? null : target ?? null, on_failure: null, retry: 0, timeout_ms: 30000 });
  parent.on_success = id;
  // A newly inserted condition retains reachability of both existing branches.
  importDag(next);
  return next;
}
