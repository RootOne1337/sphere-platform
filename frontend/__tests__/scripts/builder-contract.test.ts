import { ACTION_TYPES, exportDag, importDag, validateDag } from '@/lib/dag/export';
import fixture from '../fixtures/builder-canonical-dag.json';

it('roundtrips canonical actions, native condition parameters, all routes, retries, timeouts and polling cycles', () => {
  const imported = importDag(fixture);
  expect(imported.edges.filter((e) => e.source === 'condition')).toHaveLength(4);
  expect(exportDag(imported.nodes, imported.edges, imported.metadata)).toEqual(fixture);
  expect(validateDag(fixture)).toEqual([]);
});

it.each(ACTION_TYPES.filter((t) => t !== 'condition'))('preserves %s action parameters even without a specialized form', (type) => {
  const dag = { version: '1.0', entry_node: 'action', nodes: [
    { id: 'action', action: { type, x: 1, y: 2, x1: 1, y1: 2, x2: 3, y2: 4, ms: 1000, code: 'return true', params: { nested: ['keep', 42] }, save_to: 'result' }, on_success: 'end', on_failure: null, retry: 3, timeout_ms: 8000 },
    fixture.nodes[4],
  ], timeout_ms: 90000 };
  const graph = importDag(dag);
  expect(exportDag(graph.nodes, graph.edges, graph.metadata)).toEqual(dag);
});

it('uses the imported entry even when it is not a Start visual node', () => {
  const dag = { ...fixture, entry_node: 'tap', nodes: fixture.nodes.slice(1) };
  const graph = importDag(dag);
  expect(exportDag(graph.nodes, graph.edges, graph.metadata).entry_node).toBe('tap');
});

it('deleting a condition branch never retains a hidden original target', () => {
  const graph = importDag(fixture);
  const dag = exportDag(graph.nodes, graph.edges.filter((e) => e.sourceHandle !== 'false_branch'), graph.metadata);
  expect(dag.nodes[2].action.on_false).toBeUndefined();
  expect(validateDag(dag).join(' ')).toContain('требуется on_false');
  expect(fixture.nodes[2].action.on_false).toBe('wait');
});

it('rejects ambiguous fan-out rather than overwriting one target', () => {
  const graph = importDag(fixture);
  expect(() => exportDag(graph.nodes, [...graph.edges, { id: 'duplicate', source: 'start', target: 'end' }], graph.metadata)).toThrow('нескольким шагам');
});

it.each([
  ['legacy dictionary', { entry_node: 'start', nodes: { start: { type: 'Start', links: {} } } }],
  ['duplicate ids', { ...fixture, nodes: [...fixture.nodes, fixture.nodes[0]] }],
  ['missing target', { ...fixture, entry_node: 'missing' }],
  ['unknown action', { ...fixture, nodes: [fixture.nodes[0], { id: 'tap', action: { type: 'unsupported' } }] }],
  ['unsupported version', { ...fixture, version: '2.0' }],
  ['unreachable node', { ...fixture, nodes: [...fixture.nodes, { ...fixture.nodes[4], id: 'orphan' }] }],
  ['invalid retry', { ...fixture, nodes: [{ ...fixture.nodes[0], retry: 6 }, ...fixture.nodes.slice(1)] }],
  ['old sleep parameter', { ...fixture, nodes: fixture.nodes.map((n) => n.id === 'wait' ? { ...n, action: { type: 'sleep', duration_ms: 1000 } } : n) }],
  ['fractional coordinate', { ...fixture, nodes: fixture.nodes.map((n) => n.id === 'tap' ? { ...n, action: { type: 'tap', x: 1.5, y: 2 } } : n) }],
])('blocks %s before opening a writable graph', (_, value) => {
  expect(validateDag(value).length).toBeGreaterThan(0);
  expect(() => importDag(value)).toThrow('Запись заблокирована');
});
