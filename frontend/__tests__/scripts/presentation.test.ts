import { formatScriptStepCount, getCurrentScriptVersion, getScriptStepCount, redactScriptDag } from '@/src/features/scripts/scriptPresentation';

const version = {
  id: 'version-1',
  script_id: 'script-1',
  version: 4,
  dag: { nodes: { a: { type: 'start' }, b: { type: 'wait' } }, edges: [] },
  dag_hash: 'sha256:abc',
  notes: null,
  created_by_id: null,
  created_at: '2026-09-29T00:00:00Z',
};

describe('script presentation', () => {
  it('derives step count from the current backend DAG when no legacy count exists', () => {
    expect(getScriptStepCount({ current_version: version })).toBe(2);
    expect(getScriptStepCount({ current_version: { ...version, dag: { nodes: [{}, {}] } } })).toBe(2);
    expect(getScriptStepCount({ current_version: null })).toBeNull();
  });

  it('keeps the legacy API count and renders unknown instead of NaN/undefined', () => {
    expect(getScriptStepCount({ node_count: 12, current_version: version })).toBe(12);
    expect(formatScriptStepCount(1)).toBe('1 шаг');
    expect(formatScriptStepCount(2)).toBe('2 шага');
    expect(formatScriptStepCount(5)).toBe('5 шагов');
    expect(formatScriptStepCount(null)).toBe('Шаги не указаны');
  });

  it('masks obvious secrets recursively before an operator inspects a DAG', () => {
    expect(redactScriptDag({
      nodes: { login: { password: 'raw-password', token: 'raw-token', wait_ms: 100 } },
      safe_label: 'start',
    })).toEqual({
      nodes: { login: { password: '[скрыто]', token: '[скрыто]', wait_ms: 100 } },
      safe_label: 'start',
    });
  });

  it('recognizes the backend current_version object without treating numeric legacy data as a version object', () => {
    const script = { current_version: version };
    expect(getCurrentScriptVersion(script)).toEqual(version);
    expect(getCurrentScriptVersion({ current_version: 4 })).toBeNull();
  });
});
