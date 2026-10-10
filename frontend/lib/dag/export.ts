import { type Node, type Edge } from '@xyflow/react';

// Wire contract: backend/schemas/dag.py. Canvas coordinates never enter the DAG.
export const ACTION_TYPES = [
  'tap', 'swipe', 'type_text', 'sleep', 'find_element', 'key_event', 'lua',
  'screenshot', 'condition', 'start', 'end', 'launch_app', 'stop_app',
  'clear_app_data', 'find_first_element', 'tap_first_visible', 'tap_element',
  'get_element_text', 'wait_for_element_gone', 'scroll_to', 'long_press',
  'double_tap', 'scroll', 'set_variable', 'get_variable', 'increment_variable',
  'shell', 'input_clear', 'http_request', 'open_url', 'get_device_info', 'assert',
] as const;

export interface DagNode {
  id: string;
  action: Record<string, unknown> & { type: string };
  on_success?: string | null;
  on_failure?: string | null;
  retry?: number;
  timeout_ms?: number;
}

export interface DagExport {
  version: '1.0';
  entry_node: string;
  nodes: DagNode[];
  name?: string | null;
  description?: string | null;
  timeout_ms?: number;
}

export type DagMetadata = Omit<DagExport, 'nodes'>;
const VISUAL_TYPES: Record<string, string> = {
  start: 'Start', end: 'End', tap: 'Tap', swipe: 'Swipe', sleep: 'Sleep',
  lua: 'Lua', condition: 'Condition', screenshot: 'Screenshot',
};
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

/** Validate structure without pretending to replace APK parameter/Lua checks. */
export type DagValidationOptions = { editing?: boolean };
export function validateDag(value: unknown, options: DagValidationOptions = {}): string[] {
  const errors: string[] = [];
  if (!record(value) || !Array.isArray(value.nodes)) {
    return ['Граф должен содержать массив nodes в формате DAG 1.0.'];
  }
  if (value.version !== undefined && value.version !== '1.0') errors.push('Неподдерживаемая версия графа.');
  if (value.nodes.length < (options.editing ? 1 : 2) || value.nodes.length > 500) errors.push(options.editing ? 'Черновик должен содержать от 1 до 500 шагов.' : 'В графе должно быть от 2 до 500 шагов.');
  if (value.name != null && (typeof value.name !== 'string' || value.name.length > 255)) errors.push('Имя графа: максимум 255 символов.');
  if (value.description != null && (typeof value.description !== 'string' || value.description.length > 2000)) errors.push('Описание графа: максимум 2000 символов.');
  const integerRange = (v: unknown, min: number, max: number) =>
    typeof v === 'number' && Number.isInteger(v) && v >= min && v <= max;
  if (value.timeout_ms !== undefined && !integerRange(value.timeout_ms, 1000, 86_400_000)) errors.push('Таймаут графа: 1000–86400000 мс.');
  const ids = new Set<string>();
  const adjacency = new Map<string, string[]>();
  for (const raw of value.nodes) {
    if (!record(raw) || typeof raw.id !== 'string' || !/^[a-zA-Z_][\p{L}\p{N}_-]{0,63}$/u.test(raw.id)) {
      errors.push('Каждый шаг должен иметь корректный строковый id (до 64 символов).');
      continue;
    }
    if (ids.has(raw.id)) errors.push(`Повторяющийся id: ${raw.id}.`);
    ids.add(raw.id);
    const refs: string[] = [];
    for (const key of ['on_success', 'on_failure']) {
      if (raw[key] != null) {
        if (typeof raw[key] !== 'string' || !raw[key]) errors.push(`${raw.id}: некорректная ссылка ${key}.`);
        else refs.push(raw[key]);
      }
    }
    if (!record(raw.action) || !ACTION_TYPES.includes(raw.action.type as typeof ACTION_TYPES[number])) {
      errors.push(`${raw.id}: неизвестный тип действия.`);
    } else if (raw.action.type === 'condition') {
      for (const key of ['on_true', 'on_false']) {
        if (options.editing && raw.action[key] == null) continue;
        if (typeof raw.action[key] !== 'string' || !raw.action[key]) errors.push(`${raw.id}: требуется ${key}.`);
        else refs.push(raw.action[key]);
      }
    }
    if (record(raw.action)) {
      const action = raw.action;
      const coordinates = action.type === 'tap' ? ['x', 'y'] : action.type === 'swipe' ? ['x1', 'y1', 'x2', 'y2'] : [];
      for (const key of coordinates) if (!integerRange(action[key], 0, 2_147_483_647)) errors.push(`${raw.id}: ${key} должен быть неотрицательным целым числом.`);
      if (action.type === 'swipe' && action.duration_ms !== undefined && !integerRange(action.duration_ms, 0, 2_147_483_647)) errors.push(`${raw.id}: некорректная длительность свайпа.`);
      if (action.type === 'sleep' && !integerRange(action.ms, 0, Number.MAX_SAFE_INTEGER)) errors.push(`${raw.id}: требуется длительность ms.`);
      if (action.type === 'lua' && (typeof action.code !== 'string' || !action.code.trim())) errors.push(`${raw.id}: требуется Lua-код.`);
      if (action.type === 'condition' && !['element_exists', 'text_contains', 'battery_above'].includes(String(action.check))
        && (typeof action.code !== 'string' || !action.code.trim())) errors.push(`${raw.id}: требуется нативная проверка или Lua-код условия.`);
    }
    if (raw.retry !== undefined && !integerRange(raw.retry, 0, 5)) errors.push(`${raw.id}: повторы от 0 до 5.`);
    if (raw.timeout_ms !== undefined && !integerRange(raw.timeout_ms, 100, 3_600_000)) errors.push(`${raw.id}: таймаут шага 100–3600000 мс.`);
    adjacency.set(raw.id, refs);
  }
  if (typeof value.entry_node !== 'string' || !ids.has(value.entry_node)) errors.push('Начальный шаг не найден.');
  for (const [id, refs] of adjacency) {
    for (const ref of refs) if (!ids.has(ref)) errors.push(`${id}: ссылка на отсутствующий шаг ${ref}.`);
  }
  // Polling cycles are supported by the backend and bounded by the graph timeout.
  const seen = new Set<string>();
  const pending = typeof value.entry_node === 'string' ? [value.entry_node] : [];
  while (pending.length) {
    const id = pending.pop()!;
    if (seen.has(id)) continue;
    seen.add(id);
    pending.push(...(adjacency.get(id) ?? []));
  }
  if (!options.editing) for (const id of ids) if (!seen.has(id)) errors.push(`Шаг ${id} недостижим от начального шага.`);
  return errors;
}

export function importDag(value: unknown, options: DagValidationOptions = {}): { nodes: Node[]; edges: Edge[]; metadata: DagMetadata } {
  const errors = validateDag(value, options);
  if (errors.length) throw new Error(`Сценарий не может быть открыт: ${errors.join(' ')} Запись заблокирована.`);
  const dag = value as DagExport;
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  for (const [index, raw] of dag.nodes.entries()) {
    const type = VISUAL_TYPES[raw.action.type] ?? 'Action';
    nodes.push({
      id: raw.id, type, position: { x: 200 + (index % 3) * 250, y: 50 + Math.floor(index / 3) * 180 },
      data: { type, action: { ...raw.action }, retry: raw.retry ?? 0, timeout_ms: raw.timeout_ms ?? 30_000 },
    });
    const link = (target: string | null | undefined, sourceHandle: string | null) => {
      if (target) edges.push({ id: `e-${raw.id}-${sourceHandle ?? 'next'}-${target}`, source: raw.id, target, sourceHandle });
    };
    link(raw.on_success, null);
    link(raw.on_failure, 'failure');
    if (raw.action.type === 'condition') {
      link(raw.action.on_true as string, 'true_branch');
      link(raw.action.on_false as string, 'false_branch');
    }
  }
  return { nodes, edges, metadata: {
    version: '1.0', entry_node: dag.entry_node, timeout_ms: dag.timeout_ms ?? 1_800_000,
    ...(dag.name !== undefined ? { name: dag.name } : {}),
    ...(dag.description !== undefined ? { description: dag.description } : {}),
  } };
}

export function exportDag(nodes: Node[], edges: Edge[], metadata?: DagMetadata): DagExport {
  if (!nodes.length) throw new Error('Граф пуст.');
  const ids = new Set(nodes.map((n) => n.id));
  const routes = new Map<string, Map<string, string>>();
  for (const edge of edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target)) throw new Error('Связь содержит отсутствующий шаг.');
    const handle = edge.sourceHandle ?? 'next';
    if (!['next', 'failure', 'true_branch', 'false_branch'].includes(handle)) throw new Error(`Неизвестный выход: ${handle}.`);
    const links = routes.get(edge.source) ?? new Map<string, string>();
    if (links.has(handle)) throw new Error(`${edge.source}: один выход не может вести к нескольким шагам.`);
    links.set(handle, edge.target);
    routes.set(edge.source, links);
  }
  const exported: DagNode[] = nodes.map((node) => {
    if (!record(node.data.action) || typeof node.data.action.type !== 'string') throw new Error(`${node.id}: действие не задано.`);
    const action = { ...node.data.action } as DagNode['action'];
    const links = routes.get(node.id);
    if (action.type === 'condition') {
      // Canvas owns transitions: deleting a branch must not retain its old target.
      delete action.on_true;
      delete action.on_false;
      if (links?.has('true_branch')) action.on_true = links.get('true_branch');
      if (links?.has('false_branch')) action.on_false = links.get('false_branch');
    } else if (links?.has('true_branch') || links?.has('false_branch')) {
      throw new Error(`${node.id}: условные выходы доступны только для condition.`);
    }
    return { id: node.id, action, on_success: links?.get('next') ?? null, on_failure: links?.get('failure') ?? null,
      retry: (node.data.retry as number | undefined) ?? 0, timeout_ms: (node.data.timeout_ms as number | undefined) ?? 30_000 };
  });
  const entry = metadata?.entry_node ?? nodes.find((node) => node.type === 'Start')?.id;
  if (!entry) throw new Error('Выберите начальный шаг.');
  return { ...metadata, version: '1.0', entry_node: entry, timeout_ms: metadata?.timeout_ms ?? 1_800_000, nodes: exported };
}
