import type { Script, ScriptVersion } from '@/lib/hooks/useScripts';

export function getScriptStepCount(script: Pick<Script, 'node_count' | 'current_version'>): number | null {
  if (typeof script.node_count === 'number' && Number.isSafeInteger(script.node_count) && script.node_count >= 0) {
    return script.node_count;
  }

  const currentVersion = script.current_version;
  if (!currentVersion || typeof currentVersion !== 'object') return null;
  const nodes = currentVersion.dag?.nodes;
  if (Array.isArray(nodes)) return nodes.length;
  if (nodes && typeof nodes === 'object') return Object.keys(nodes).length;
  return null;
}

export function formatScriptStepCount(count: number | null): string {
  if (count == null) return 'Шаги не указаны';
  const mod10 = count % 10;
  const mod100 = count % 100;
  const noun = mod10 === 1 && mod100 !== 11
    ? 'шаг'
    : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
      ? 'шага'
      : 'шагов';
  return `${count} ${noun}`;
}

const SENSITIVE_KEY = /password|secret|token|credential|authorization|api[_-]?key|private[_-]?key/i;

/** Mask obvious credential fields before placing a DAG in an operator-readable code panel. */
export function redactScriptDag(value: unknown, depth = 0): unknown {
  if (depth >= 24) return '[глубина скрыта]';
  if (Array.isArray(value)) return value.map((entry) => redactScriptDag(entry, depth + 1));
  if (!value || typeof value !== 'object') return value;

  return Object.fromEntries(Object.entries(value).map(([key, entry]) => [
    key,
    SENSITIVE_KEY.test(key) ? '[скрыто]' : redactScriptDag(entry, depth + 1),
  ]));
}

export function getCurrentScriptVersion(script: Pick<Script, 'current_version'>): ScriptVersion | null {
  return script.current_version && typeof script.current_version === 'object'
    ? script.current_version
    : null;
}
