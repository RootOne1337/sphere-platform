import { TextEncoder } from 'node:util';
import { addDetachedAction, formatDag, initialDag, insertAction, parseDraftSource, parseSource } from '@/lib/dag/studio';
import { exportDag, importDag, validateDag } from '@/lib/dag/export';
import { draggedAction, freeCanvasPosition, mergeCanvasPositions } from '@/lib/dag/canvasPlacement';
import fixture from '../fixtures/builder-canonical-dag.json';
Object.assign(globalThis, { TextEncoder });

it('keeps every old transition intact when adding a disconnected step', () => {
  const before = formatDag(initialDag);
  const next = addDetachedAction(initialDag, 'tap', 'separate');
  expect(next.nodes.slice(0, 2)).toEqual(initialDag.nodes);
  expect(next.nodes[2]).toMatchObject({ id: 'separate', action: { type: 'tap' }, on_success: null, on_failure: null });
  expect(formatDag(initialDag)).toBe(before);
  expect(parseDraftSource(formatDag(next))).toEqual(next);
  expect(() => parseSource(formatDag(next))).toThrow('недостижим');
  expect(() => importDag(next)).toThrow('недостижим');
});
it('roundtrips incomplete conditions without manufacturing routes and still rejects publication', () => {
  const next = addDetachedAction(initialDag, 'condition', 'branch');
  next.nodes[0].on_success = 'branch';
  const flow = importDag(next, { editing: true });
  expect(exportDag(flow.nodes, flow.edges, flow.metadata)).toEqual(next);
  expect(validateDag(next)).toEqual(expect.arrayContaining(['branch: требуется on_true.', 'branch: требуется on_false.']));
  const connected = exportDag(flow.nodes, [...flow.edges,
    { id: 'true', source: 'branch', sourceHandle: 'true_branch', target: 'end-1' },
    { id: 'false', source: 'branch', sourceHandle: 'false_branch', target: 'end-1' },
  ], flow.metadata);
  expect(parseSource(formatDag(connected))).toEqual(connected);
});
it('lets an operator rebuild a one-step draft while the publish minimum remains two steps', () => {
  const one = { ...initialDag, nodes: [{ ...initialDag.nodes[0], on_success: null }] };
  expect(parseDraftSource(formatDag(one))).toEqual(one);
  expect(() => parseSource(formatDag(one))).toThrow('от 2 до 500');
  expect(addDetachedAction(one, 'end', 'new_end').nodes).toHaveLength(2);
  expect(() => parseDraftSource(formatDag({ ...one, nodes: [] }))).toThrow();
});
it.each([
  { ...fixture, entry_node: 'missing' },
  { ...fixture, nodes: [...fixture.nodes, fixture.nodes[0]] },
  { ...fixture, nodes: fixture.nodes.map(node => node.id === 'tap' ? { ...node, on_success: 'absent' } : node) },
  { ...fixture, nodes: fixture.nodes.map(node => node.id === 'condition' ? { ...node, action: { ...node.action, on_false: '' } } : node) },
  { ...fixture, nodes: fixture.nodes.map(node => node.id === 'condition' ? { ...node, action: { ...node.action, on_true: 123 } } : node) },
  { ...fixture, nodes: fixture.nodes.map(node => node.id === 'tap' ? { ...node, action: { type: 'unknown' } } : node) },
  { ...fixture, timeout_ms: 0 },
])('never relaxes identities, references, action types or budgets for editing', value => {
  expect(() => parseDraftSource(JSON.stringify(value))).toThrow();
});
it('permits an explicit linear insertion while another disconnected step remains editable', () => {
  const draft = addDetachedAction(initialDag, 'sleep', 'detached');
  const next = insertAction(draft, 'tap', 'inserted', 'start-1');
  expect(next.nodes[0].on_success).toBe('inserted');
  expect(next.nodes.find(node => node.id === 'inserted')?.on_success).toBe('end-1');
  expect(next.nodes.find(node => node.id === 'detached')).toEqual(draft.nodes[2]);
  expect(() => parseSource(formatDag(next))).toThrow('detached');
});
it('rejects unknown actions, duplicate IDs and excess nodes without mutating the draft', () => {
  expect(() => addDetachedAction(initialDag, 'loop' as never, 'x')).toThrow('Неизвестное');
  expect(() => addDetachedAction(initialDag, 'tap', 'start-1')).toThrow('ID');
  const full = { ...initialDag, nodes: Array.from({ length: 500 }, (_, index) => ({ ...initialDag.nodes[1], id: `node_${index}` })) };
  expect(() => addDetachedAction(full, 'tap', 'extra')).toThrow('500');
  expect(full.nodes).toHaveLength(500);
});
it('accepts only exact published action drag data', () => {
  expect(draggedAction('tap')).toBe('tap');
  for (const value of ['loop', 'tap ', '{"type":"tap"}', '__proto__', '']) expect(draggedAction(value)).toBeNull();
});
it('finds a nearby vacant click position using measured node bounds without moving old nodes', () => {
  const nodes = [{ id: 'a', data: {}, position: { x: 0, y: 0 }, measured: { width: 300, height: 160 } }];
  const before = JSON.stringify(nodes);
  const result = freeCanvasPosition(nodes, { x: 20, y: 20 });
  expect(result).not.toEqual({ x: 20, y: 20 });
  expect(freeCanvasPosition(nodes, { x: 1000, y: 1000 })).toEqual({ x: 1000, y: 1000 });
  expect(JSON.stringify(nodes)).toBe(before);
  expect(() => freeCanvasPosition(nodes, { x: NaN, y: 2 })).toThrow('позиция');
});

it('reserves retained positions before placing an inserted step, even when the existing end comes later', () => {
  const previous = [{ id: 'start', data: {}, position: { x: 0, y: 0 } },
    { id: 'end', data: {}, position: { x: 0, y: 210 }, measured: { width: 320, height: 160 } }];
  const before = JSON.stringify(previous);
  const arranged = [previous[0], { id: 'inserted', data: {}, position: { x: 0, y: 210 } },
    { ...previous[1], position: { x: 0, y: 420 } }];
  const result = mergeCanvasPositions(arranged, previous);
  expect(result.find(node => node.id === 'start')?.position).toEqual({ x: 0, y: 0 });
  expect(result.find(node => node.id === 'end')?.position).toEqual({ x: 0, y: 210 });
  const inserted = result.find(node => node.id === 'inserted')!.position;
  expect(inserted.x >= 344 || inserted.x + 280 <= 0 || inserted.y >= 394 || inserted.y + 156 <= 210).toBe(true);
  expect(JSON.stringify(previous)).toBe(before);
});

it('places several recorded steps without covering retained nodes or each other', () => {
  const previous = [{ id: 'end', data: {}, position: { x: 0, y: 210 } }];
  const result = mergeCanvasPositions([
    { id: 'recorded-key', data: {}, position: { x: 0, y: 210 } },
    { id: 'recorded-selector', data: {}, position: { x: 0, y: 210 } }, previous[0],
  ], previous);
  for (let a = 0; a < result.length; a++) for (let b = a + 1; b < result.length; b++) {
    const p = result[a].position; const q = result[b].position;
    expect(p.x + 256 <= q.x || q.x + 256 <= p.x || p.y + 132 <= q.y || q.y + 132 <= p.y).toBe(true);
  }
});

it('keeps deliberate drop and parameter edits in their exact positions; removed nodes reserve no space', () => {
  const existing = { id: 'end', data: {}, position: { x: 0, y: 210 } };
  const incoming = { id: 'drop', data: {}, position: { x: 0, y: 0 } };
  expect(mergeCanvasPositions([existing, incoming], [existing], { id: 'drop', x: 0, y: 210 })[1].position).toEqual(existing.position);
  expect(mergeCanvasPositions([{ ...existing, data: { changed: true } }], [existing])[0].position).toEqual(existing.position);
  expect(mergeCanvasPositions([incoming], [existing])[0].position).toEqual(incoming.position);
});
