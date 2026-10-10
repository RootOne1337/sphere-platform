import rawContract from './action-contract.v1.json';

type Rule = {
  ref?: string; required?: boolean; type?: string; min?: number; max?: number; nonblank?: boolean;
  enum?: string[]; case?: 'upper'; pattern?: string; format?: 'http_url';
  fields?: Record<string, Rule>; items?: Rule; values?: Rule; key_pattern?: string;
};
export interface ActionSpec {
  effect: 'flow' | 'control' | 'destructive' | 'read' | 'context' | 'code' | 'network';
  fields: Record<string, Rule>; checks?: Record<string, Rule>; fallback_field?: string; note: string;
}
interface Contract { version: string; messages: Record<string, string>; definitions: Record<string, Rule>;
  common_fields: Record<string, Rule>; actions: Record<string, ActionSpec> }
// Generated build copy; backend/schemas/action_contract.v1.json is authoritative.
export const actionContract = rawContract as unknown as Contract;
export const ACTION_CONTRACT_VERSION = actionContract.version;
export interface ActionParameterError { loc: (string | number)[]; type: string; msg: string }
const isObject = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const owns = (value: object, key: string) => Object.prototype.hasOwnProperty.call(value, key);
export const fieldRule = (rule: Rule): Rule => ({ ...actionContract.definitions[rule.ref ?? ''], ...rule });

/** Same bounded rules as the API, with no coercion, defaults or private values in errors. */
export function actionParameterErrors(nodes: { action: Record<string, unknown> }[]): ActionParameterError[] {
  const errors: ActionParameterError[] = [];
  const seen = new Set<string>();
  const fail = (loc: (string | number)[], code: string) => {
    const key = JSON.stringify([loc, code]);
    if (errors.length < 100 && !seen.has(key)) { seen.add(key); errors.push({ loc, type: `action_parameter.${code}`, msg: actionContract.messages[code] }); }
  };
  function visit(value: unknown, rawRule: Rule, path: (string | number)[], present = true) {
    if (errors.length >= 100) return;
    const rule = fieldRule(rawRule);
    if (!present) { if (rule.required) fail(path, 'required'); return; }
    const kind = rule.type!;
    const valid = kind === 'integer' ? typeof value === 'number' && Number.isInteger(value)
      : kind === 'number' ? typeof value === 'number' && Number.isFinite(value)
      : kind === 'boolean' ? typeof value === 'boolean'
      : kind === 'string' ? typeof value === 'string'
      : kind === 'object' ? isObject(value)
      : kind === 'array' ? Array.isArray(value)
      : kind === 'primitive' ? value === null || typeof value === 'string' || typeof value === 'boolean' || typeof value === 'number' && Number.isFinite(value)
      : false;
    if (!valid) { fail(path, kind); return; }
    if ((kind === 'integer' || kind === 'number') && (rule.min !== undefined && (value as number) < rule.min || rule.max !== undefined && (value as number) > rule.max)) fail(path, 'range');
    if (['string', 'array', 'object'].includes(kind)) {
      const length = typeof value === 'string' ? Array.from(value).length : Array.isArray(value) ? value.length : Object.keys(value as object).length;
      if (rule.min !== undefined && length < rule.min || rule.max !== undefined && length > rule.max || rule.nonblank && !(value as string).trim()) { fail(path, 'length'); return; }
    }
    if (rule.enum && !rule.enum.includes(rule.case === 'upper' ? (value as string).toUpperCase() : value as string)) fail(path, 'enum');
    if (rule.pattern && !(new RegExp(`^(?:${rule.pattern})$`)).test(value as string)) fail(path, 'pattern');
    if (rule.format === 'http_url') {
      try { const url = new URL(value as string); if (!/^https?:\/\//.test(value as string) || !url.hostname || /\s/.test(value as string)) fail(path, 'http_url'); }
      catch { fail(path, 'http_url'); }
    }
    if (kind === 'array' && rule.items) (value as unknown[]).forEach((item, index) => visit(item, rule.items!, [...path, index]));
    if (kind === 'object') {
      const object = value as Record<string, unknown>;
      for (const [key, child] of Object.entries(rule.fields ?? {})) visit(object[key], child, [...path, key], owns(object, key));
      if (rule.values) for (const [key, item] of Object.entries(object)) {
        // Don't echo arbitrary header names into error paths or operational logs.
        const childPath = [...path, '<entry>'];
        if (!(new RegExp(`^(?:${rule.key_pattern})$`)).test(key)) fail(childPath, 'pattern');
        visit(item, rule.values, childPath);
      }
    }
  }
  for (const [index, node] of nodes.entries()) {
    if (errors.length >= 100) break;
    const action = node.action, path = ['nodes', index, 'action'];
    const type = typeof action.type === 'string' ? action.type : '';
    const spec = owns(actionContract.actions, type) ? actionContract.actions[type] : undefined;
    if (!spec) { fail([...path, 'type'], 'type'); continue; }
    visit(action, { type: 'object', fields: { ...actionContract.common_fields, ...spec.fields } }, path);
    if (spec.checks) {
      const check = typeof action.check === 'string' ? action.check : '';
      if (owns(spec.checks, check)) visit(action.params, spec.checks[check], [...path, 'params'], owns(action, 'params'));
      else if (!(spec.fallback_field && typeof action[spec.fallback_field] === 'string' && (action[spec.fallback_field] as string).trim())) fail([...path, 'check'], 'check');
    }
  }
  return errors;
}
