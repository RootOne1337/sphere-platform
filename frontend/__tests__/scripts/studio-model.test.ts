import { TextEncoder } from 'node:util';
import { ACTION_TYPES } from '@/lib/dag/export';
import { initialDag, formatDag, parseSource, byteLength, boundedSource, SOURCE_LIMIT, DRAFT_TTL, readDraft, writeDraft, draftKey, pushHistory, insertAction, defaultAction, arrangeNodes } from '@/lib/dag/studio';
import { importDag } from '@/lib/dag/export';
Object.assign(globalThis, { TextEncoder });
const source = formatDag(initialDag);
const document = { name: 'Сценарий', source };
it('enforces a byte limit including multibyte Russian source without truncation', () => {
  expect(byteLength('я')).toBe(2);
  expect(() => boundedSource('я'.repeat(SOURCE_LIMIT / 2 + 1))).toThrow('512 KiB');
  expect(boundedSource('a'.repeat(SOURCE_LIMIT))).toHaveLength(SOURCE_LIMIT);
});
it('lays out execution order rather than source array order, and terminates for cycles', () => {
  const dag = insertAction(initialDag, 'sleep', 'wait');
  const imported = importDag(dag);
  const layout = arrangeNodes(imported.nodes, imported.edges, dag.entry_node);
  expect(layout.find(node => node.id === 'start-1')!.position.x).toBeLessThan(layout.find(node => node.id === 'wait')!.position.x);
  expect(layout.find(node => node.id === 'wait')!.position.x).toBeLessThan(layout.find(node => node.id === 'end-1')!.position.x);
  expect(new Set(layout.map(node => JSON.stringify(node.position))).size).toBe(3);
  expect(arrangeNodes(imported.nodes, [...imported.edges, { id: 'loop', source: 'end-1', target: 'wait' }], dag.entry_node)).toHaveLength(3);
  expect(imported.nodes[0].position).toEqual({ x: 200, y: 50 });
});
it('rejects excessive encoded draft overhead before writing an unrecoverable envelope', () => {
  expect(() => writeDraft({ ...document, source: '\\'.repeat(SOURCE_LIMIT) }, 'a')).toThrow('JSON-кодирования');
});
it('rejects invalid source instead of substituting a previous graph', () => {
  expect(() => parseSource('{ broken')).toThrow('Некорректный JSON');
  expect(() => parseSource(JSON.stringify({ ...initialDag, entry_node: 'missing' }))).toThrow('Начальный шаг');
});
it.each(ACTION_TYPES)('inserts %s with canonical structure and preserves the existing document', type => {
  const next = insertAction(initialDag, type, 'inserted');
  expect(parseSource(formatDag(next)).nodes).toHaveLength(3);
  expect(next.nodes[0].on_success).toBe('inserted');
  expect(initialDag.nodes[0].on_success).toBe('end-1');
});
it('inserts both condition branches without losing the original terminal target', () => {
  const next = insertAction(initialDag, 'condition', 'branch');
  expect(next.nodes[2].action).toMatchObject({ on_true: 'end-1', on_false: 'end-1' });
});
it('does not share nested action templates between nodes', () => {
  const one = defaultAction('assert'); (one.params as { selector: string }).selector = 'changed';
  expect((defaultAction('assert').params as { selector: string }).selector).not.toBe('changed');
});
it('caps history by count and total bytes, preserving the most recent edit', () => {
  let history = Array.from({ length: 20 }, (_, index) => ({ name: String(index), source }));
  history = pushHistory(history, document);
  expect(history).toHaveLength(20); expect(history.at(-1)).toEqual(document);
  history = pushHistory(history, { ...document, source: 'a'.repeat(SOURCE_LIMIT) });
  history = pushHistory(history, { ...document, source: 'b'.repeat(SOURCE_LIMIT) });
  history = pushHistory(history, { ...document, source: 'c'.repeat(SOURCE_LIMIT) });
  history = pushHistory(history, { ...document, source: 'd'.repeat(SOURCE_LIMIT) });
  expect(history.reduce((sum, value) => sum + byteLength(JSON.stringify(value)), 0)).toBeLessThanOrEqual(2 * 1024 * 1024);
  expect(history.at(-1)?.source[0]).toBe('d');
});
it('isolates draft keys by identity and restores only the matching unexpired resource', () => {
  expect(draftKey('one', 'a')).not.toBe(draftKey('two', 'a'));
  expect(draftKey('one', 'a')).not.toBe(draftKey('one', 'b'));
  const raw = writeDraft(document, 'script-a', 1000);
  expect(readDraft(raw, 'script-a', 2000)).toEqual(document);
  expect(readDraft(raw, 'script-b', 2000)).toBeNull();
  expect(readDraft(raw, 'script-a', 1001 + DRAFT_TTL)).toBeNull();
  expect(readDraft(raw, 'script-a', -100000)).toBeNull();
});
it('allows an invalid JSON draft for repair, but rejects malformed envelopes and oversize payloads', () => {
  expect(readDraft(writeDraft({ ...document, source: 'broken' }, 'a', 1000), 'a', 2000)?.source).toBe('broken');
  expect(() => readDraft('bad', 'a')).toThrow('повреждён');
  expect(() => writeDraft({ ...document, source: 'я'.repeat(SOURCE_LIMIT) }, 'a')).toThrow('512 KiB');
});
