import { changeConnection, checkConnection } from '@/lib/dag/connections';
import { exportDag, importDag, type DagExport } from '@/lib/dag/export';

const dag: DagExport = { version: '1.0', entry_node: 'start', nodes: [
  { id: 'start', action: { type: 'start' }, on_success: 'check' },
  { id: 'check', action: { type: 'condition', check: 'battery_above', on_true: 'done', on_false: 'again' }, on_failure: 'done' },
  { id: 'again', action: { type: 'sleep', ms: 100 }, on_success: 'check' },
  { id: 'done', action: { type: 'end' } },
] };

it('moves one conditional branch without rewriting the other branches and keeps its canvas identity', () => {
  const { nodes, edges, metadata } = importDag(dag);
  const yes = edges.find(edge => edge.sourceHandle === 'true_branch')!;
  const next = changeConnection(nodes, edges, yes.id, { source: 'check', sourceHandle: 'true_branch', target: 'again', targetHandle: null });
  expect(exportDag(nodes, next, metadata).nodes.find(node => node.id === 'check')).toMatchObject({
    action: { on_true: 'again', on_false: 'again' }, on_failure: 'done',
  });
  expect(next.find(edge => edge.id === yes.id)?.target).toBe('again');
  expect(edges.find(edge => edge.id === yes.id)?.target).toBe('done');
});
it('can reconnect an incomplete draft without retaining a deleted wire target', () => {
  const { nodes, edges, metadata } = importDag(dag);
  const removed = edges.filter(edge => edge.sourceHandle !== 'true_branch');
  expect(exportDag(nodes, removed, metadata).nodes.find(node => node.id === 'check')?.action).not.toHaveProperty('on_true');
  checkConnection(nodes, removed, { source: 'check', sourceHandle: 'true_branch', target: 'done', targetHandle: null });
});
it('rejects a source outlet collision without replacing either branch', () => {
  const { nodes, edges } = importDag(dag);
  const yes = edges.find(edge => edge.sourceHandle === 'true_branch')!;
  expect(() => changeConnection(nodes, edges, yes.id, { source: 'check', sourceHandle: 'false_branch', target: 'done', targetHandle: null })).toThrow('уже соединён');
  expect(edges.find(edge => edge.id === yes.id)?.sourceHandle).toBe('true_branch');
});
it.each([
  { source: 'missing', sourceHandle: null, target: 'done', targetHandle: null },
  { source: 'done', sourceHandle: null, target: 'again', targetHandle: null },
  { source: 'again', sourceHandle: 'true_branch', target: 'done', targetHandle: null },
  { source: 'again', sourceHandle: null, target: 'start', targetHandle: null },
  { source: 'again', sourceHandle: null, target: 'done', targetHandle: 'unknown' },
])('rejects endpoints that the node does not expose: %j', connection => {
  const { nodes, edges } = importDag(dag);
  expect(() => checkConnection(nodes, edges, connection)).toThrow();
});
it('retains a legacy condition success route while changing only its target', () => {
  const { nodes, edges, metadata } = importDag({ ...dag, nodes: dag.nodes.map(node => node.id === 'check' ? { ...node, on_success: 'done' } : node) });
  const legacy = edges.find(edge => edge.source === 'check' && edge.sourceHandle === null)!;
  const next = changeConnection(nodes, edges, legacy.id, { source: 'check', sourceHandle: null, target: 'again', targetHandle: null });
  expect(exportDag(nodes, next, metadata).nodes.find(node => node.id === 'check')).toMatchObject({ on_success: 'again', action: { on_true: 'done', on_false: 'again' } });
});
it('rejects a stale reconnect event for a deleted edge', () => {
  const { nodes, edges } = importDag(dag);
  expect(() => changeConnection(nodes, [], edges[0].id, { source: 'start', target: 'done', sourceHandle: null, targetHandle: null })).toThrow('уже удалена');
});
