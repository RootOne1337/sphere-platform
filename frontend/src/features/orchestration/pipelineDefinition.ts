import { redactScriptDag } from '@/src/features/scripts/scriptPresentation';

export interface PipelineDefinition {
  id: string; org_id: string; name: string; description: string | null;
  steps: Record<string, unknown>[]; input_schema: Record<string, unknown>;
  global_timeout_ms: number; max_retries: number; version: number; is_active: boolean;
  tags: string[]; created_by_id: string | null; created_at: string; updated_at: string;
}
export type DefinitionPatch = Partial<Pick<PipelineDefinition, 'name' | 'description' | 'steps' | 'input_schema' | 'global_timeout_ms' | 'tags'>>;
export type DefinitionDraft = { name: string; description: string; steps: string; input_schema: string; global_timeout_ms: string; tags: string };
const record = (v: unknown): v is Record<string, unknown> => Boolean(v && typeof v === 'object' && !Array.isArray(v));
const integer = (v: unknown, min: number, max: number): v is number => Number.isInteger(v) && Number(v) >= min && Number(v) <= max;
const timestamp = (v: unknown): v is string => typeof v === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const types = new Set(['execute_script', 'condition', 'action', 'delay', 'parallel', 'wait_for_event', 'n8n_workflow', 'loop', 'sub_pipeline']);
export function canonical(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (record(value)) return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
export function parsePipelineDefinition(data: unknown, id: string, org: string): PipelineDefinition {
  if (!record(data) || data.id !== id || data.org_id !== org || typeof data.name !== 'string'
    || !(data.description === null || typeof data.description === 'string')
    || !Array.isArray(data.steps) || !data.steps.every(record) || !record(data.input_schema)
    || !integer(data.global_timeout_ms, 10000, 259200000) || !integer(data.max_retries, 0, 5)
    || !integer(data.version, 1, Number.MAX_SAFE_INTEGER) || typeof data.is_active !== 'boolean'
    || !Array.isArray(data.tags) || !data.tags.every(v => typeof v === 'string')
    || !(data.created_by_id === null || typeof data.created_by_id === 'string')
    || !timestamp(data.created_at) || !timestamp(data.updated_at)) throw new Error('Unconfirmed pipeline identity or contents');
  return data as unknown as PipelineDefinition;
}
export function definitionDraft(value: PipelineDefinition): DefinitionDraft {
  return { name: value.name, description: value.description ?? '', steps: JSON.stringify(value.steps, null, 2),
    input_schema: JSON.stringify(value.input_schema, null, 2), global_timeout_ms: String(value.global_timeout_ms), tags: JSON.stringify(value.tags) };
}
export function validateDefinitionDraft(draft: DefinitionDraft, baseline: PipelineDefinition): DefinitionPatch {
  if (!draft.name.trim() || draft.name.length > 255) throw new Error('Название: от 1 до 255 символов.');
  const parsed = (text: string, label: string): unknown => { try { return JSON.parse(text); } catch { throw new Error(label + ': некорректный JSON.'); } };
  const rawSteps = parsed(draft.steps, 'Шаги');
  if (!Array.isArray(rawSteps) || !rawSteps.every(record)) throw new Error('Шаги: требуется JSON-массив объектов.');
  const stepsChanged = canonical(rawSteps) !== canonical(baseline.steps);
  // Preserve legacy snapshots on metadata-only edits. Normalize omitted API
  // defaults only when the operator actually changes the step definition.
  const steps: Record<string, unknown>[] = stepsChanged ? rawSteps.map(step => ({ params: {}, on_success: null, on_failure: null, timeout_ms: 60000, retries: 0, ...step })) : rawSteps;
  if (stepsChanged && (steps.length < 1 || steps.length > 100)) throw new Error('Шаги: требуется массив из 1–100 объектов.');
  const ids = new Set<string>();
  for (const step of stepsChanged ? steps : []) {
    if (typeof step.id !== 'string' || !step.id || step.id.length > 128 || ids.has(step.id)) throw new Error('Шаги: ID должны быть непустыми и уникальными (до 128 символов).');
    ids.add(step.id);
    if (typeof step.name !== 'string' || !step.name || step.name.length > 255 || !types.has(String(step.type))
      || !record(step.params) || !integer(step.timeout_ms, 1000, 3600000) || !integer(step.retries, 0, 10)) throw new Error('Шаги: проверьте имя, тип, параметры, таймаут и повторы.');
  }
  for (const step of stepsChanged ? steps : []) for (const target of [step.on_success, step.on_failure]) {
    if (target !== null && (typeof target !== 'string' || !ids.has(target))) throw new Error('Шаги: переход должен ссылаться на существующий ID или быть null.');
  }
  const schema = parsed(draft.input_schema, 'Входная схема');
  const tags = parsed(draft.tags, 'Теги');
  if (!record(schema)) throw new Error('Входная схема: требуется JSON-объект.');
  if (!Array.isArray(tags) || tags.length > 20 || !tags.every(v => typeof v === 'string')) throw new Error('Теги: до 20 строк в JSON-массиве.');
  const timeout = Number(draft.global_timeout_ms);
  if (!draft.global_timeout_ms.trim() || !integer(timeout, 10000, 259200000)) throw new Error('Глобальный таймаут: целое число от 10000 до 259200000 мс.');
  const candidate: DefinitionPatch = { name: draft.name, description: draft.description === '' ? null : draft.description,
    steps, input_schema: schema, tags, global_timeout_ms: timeout };
  return Object.fromEntries(Object.entries(candidate).filter(([key, value]) => canonical(value) !== canonical(baseline[key as keyof PipelineDefinition]))) as DefinitionPatch;
}
export function verifyDefinitionReceipt(data: unknown, baseline: PipelineDefinition, patch: DefinitionPatch | { is_active: boolean }): PipelineDefinition {
  const result = parsePipelineDefinition(data, baseline.id, baseline.org_id);
  for (const [field, value] of Object.entries(patch)) if (canonical(result[field as keyof PipelineDefinition]) !== canonical(value)) throw new Error('Mutation receipt does not match requested values');
  for (const field of ['name', 'description', 'steps', 'input_schema', 'global_timeout_ms', 'max_retries', 'tags', 'is_active'] as const) {
    if (!(field in patch) && canonical(result[field]) !== canonical(baseline[field])) throw new Error('Unexpected mutation receipt');
  }
  const version = baseline.version + ('steps' in patch && canonical(patch.steps) !== canonical(baseline.steps) ? 1 : 0);
  if (result.version !== version || result.created_at !== baseline.created_at || result.created_by_id !== baseline.created_by_id
    || Date.parse(result.updated_at) < Date.parse(baseline.updated_at)) throw new Error('Unconfirmed mutation revision');
  return result;
}
export const presentDefinition = (value: unknown) => JSON.stringify(redactScriptDag(value), null, 2);
export function definitionFailure(error: unknown): { message: string; uncertain: boolean } {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
  if (response?.status === 403) return { message: 'Нет права изменять pipeline. Проверьте роль и обновите состояние.', uncertain: false };
  if (response?.status === 404) return { message: 'Pipeline недоступен в текущей организации. Обновите каталог.', uncertain: false };
  if (response?.status === 409) return { message: 'Конфликт: pipeline изменён, занят записью или имеет действующие запуски. Черновик сохранён; перечитайте состояние перед новым подтверждением.', uncertain: false };
  if (response?.status === 422) return { message: 'Сервер отклонил поля определения. Проверьте JSON, границы и ссылки шагов; запись не подтверждена.', uncertain: false };
  return { message: 'Результат записи неизвестен. Повтор заблокирован до явного чтения состояния; не отправляйте изменение повторно автоматически.', uncertain: true };
}
