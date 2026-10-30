import { appendRecording, appendSelectorRecording, observeAcknowledgedRecording, recordingActions } from '@/src/features/scripts/studio/recording';
import type { UiHierarchyNode, UiHierarchySnapshot } from '@/src/features/stream/uiHierarchy';

const deviceId = 'owned-device';
const node: UiHierarchyNode = { id: 0, parent_id: null, depth: 0, xpath: '/hierarchy/node[1]', bounds: { left: 1, top: 2, right: 10, bottom: 20 }, attributes: { text: 'private fixture' } };
const snapshot: UiHierarchySnapshot = { device_id: deviceId, snapshot_id: 'a'.repeat(32), source: 'android_uiautomator_root', width: 960, height: 540, rotation: 0,
  requested_at: '2026-10-06T00:00:00Z', completed_at: '2026-10-06T00:00:01Z', temporary_file_cleanup_confirmed: true, nodes: [node] };
beforeEach(() => { let sequence = 0; Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: () => `record-${++sequence}` }); });

it('preserves tap / explicitly planned XPath / tap order without claiming execution or copying private node attributes', () => {
  const tap = { deviceId, at: 1000, dimensions: { width: 960, height: 540 }, command: { type: 'click' as const, x: 480, y: 270 } };
  const first = appendRecording([], tap, deviceId);
  const planned = appendSelectorRecording(first, node, snapshot, deviceId, 2000);
  const finished = appendRecording(planned, { ...tap, at: 3000 }, deviceId);
  expect(planned[1]).toMatchObject({ outcome: 'selector-planned', selectorSnapshot: { id: snapshot.snapshot_id, nodeId: 0, rotation: 0 } });
  expect(JSON.stringify(planned[1])).not.toContain('private fixture');
  expect(recordingActions(finished, false)).toEqual([
    { type: 'tap', x: 640, y: 360 },
    { type: 'tap_element', selector: node.xpath, strategy: 'xpath', timeout_ms: 5000 },
    { type: 'tap', x: 640, y: 360 },
  ]);
  expect(first).toHaveLength(1);
});
it.each([
  { device_id: 'foreign' }, { snapshot_id: '../invalid' }, { width: 0 }, { height: 20000 }, { rotation: 4 }, { nodes: [] },
])('rejects foreign/invalid hierarchy context without changing existing entries: %j', patch => {
  const entries = appendSelectorRecording([], node, snapshot, deviceId, 1000);
  expect(() => appendSelectorRecording(entries, node, { ...snapshot, ...patch }, deviceId, 2000)).toThrow('XPath');
  expect(entries).toHaveLength(1);
});
it('rejects another node, malformed and oversized selectors before retaining them', () => {
  expect(() => appendSelectorRecording([], { ...node, id: 1 }, snapshot, deviceId, 1000)).toThrow('XPath');
  for (const candidate of [{ ...node, xpath: '//*' }, { ...node, xpath: '/hierarchy' + '/node[1]'.repeat(300) }]) {
    expect(() => appendSelectorRecording([], candidate, { ...snapshot, nodes: [candidate] }, deviceId, 1000)).toThrow('XPath');
  }
});
it('applies the common 200-action cap and rejects backward/non-finite timestamps', () => {
  const entries = appendSelectorRecording([], node, snapshot, deviceId, 1000);
  expect(() => appendSelectorRecording(Array(200).fill(entries[0]), node, snapshot, deviceId, 2000)).toThrow('200');
  for (const at of [999, NaN, Infinity]) expect(() => appendSelectorRecording(entries, node, snapshot, deviceId, at)).toThrow('порядок времени');
});
it('does not let a late Android receipt confirm an explicitly planned selector', () => {
  const entries = appendSelectorRecording([], node, snapshot, deviceId, 1000);
  const input = { deviceId, at: 1000, dimensions: { width: 960, height: 540 }, command: { type: 'key_event' as const, keycode: 3 } };
  const next = observeAcknowledgedRecording(entries, { requestId: entries[0].id, input, phase: 'confirmed', completedAt: 2000 }, deviceId, false);
  expect(next).toBe(entries);
  expect(next[0].outcome).toBe('selector-planned');
});
