import { checkedHierarchy, frameBounds, hitTestHierarchy, matchesFrame, type UiHierarchySnapshot } from '@/src/features/stream/uiHierarchy';

const fixture = (): UiHierarchySnapshot => ({ device_id: 'remote', snapshot_id: 'a'.repeat(32),
  requested_at: '2026-10-03T21:00:00Z', completed_at: '2026-10-03T21:00:02Z', source: 'android_uiautomator_root',
  width: 960, height: 540, rotation: 1, temporary_file_cleanup_confirmed: true, nodes: [
    { id: 0, parent_id: null, depth: 0, xpath: '/hierarchy/node[1]', attributes: { class: 'root' }, bounds: { left: 0, top: 0, right: 960, bottom: 540 } },
    { id: 1, parent_id: 0, depth: 1, xpath: '/hierarchy/node[1]/node[1]', attributes: { text: '<script>plain text</script>' }, bounds: { left: 100, top: 100, right: 200, bottom: 150 } },
  ] });

it('keeps raw attributes and positional XPath, selecting the deepest visible child', () => {
  const snapshot = checkedHierarchy(fixture(), 'remote');
  expect(hitTestHierarchy(snapshot, 120, 120)?.id).toBe(1);
  expect(hitTestHierarchy(snapshot, 200, 120)?.id).toBe(0);
  expect(hitTestHierarchy(snapshot, 1000, 120)).toBeNull();
  expect(snapshot.nodes[1].attributes.text).toContain('<script>');
});
it('maps native bounds onto scaled landscape video without assuming portrait', () => {
  const snapshot = fixture();
  expect(matchesFrame(snapshot, { width: 1280, height: 720 })).toBe(true);
  expect(matchesFrame(snapshot, { width: 540, height: 960 })).toBe(false);
  expect(matchesFrame(snapshot, null)).toBe(false);
  expect(frameBounds(snapshot.nodes[1].bounds!, snapshot, { width: 1920, height: 1080 })).toEqual({ left: 200, top: 200, right: 400, bottom: 300 });
});
it.each([
  (s: UiHierarchySnapshot) => { s.device_id = 'other'; },
  (s: UiHierarchySnapshot) => { s.width = 0; },
  (s: UiHierarchySnapshot) => { s.rotation = 4; },
  (s: UiHierarchySnapshot) => { s.completed_at = 'bad'; },
  (s: UiHierarchySnapshot) => { s.nodes[1].parent_id = 10; },
  (s: UiHierarchySnapshot) => { s.nodes[1].attributes.text = 'x'.repeat(4097); },
  (s: UiHierarchySnapshot) => { s.nodes[1].bounds!.right = 10000; },
  (s: UiHierarchySnapshot) => { s.nodes[1].xpath = '//arbitrary'; },
])('rejects wrong owner, invalid geometry, bounds, attributes or snapshot structure %#', mutate => {
  const snapshot = fixture(); mutate(snapshot);
  expect(() => checkedHierarchy(snapshot, 'remote')).toThrow();
});

export { fixture as hierarchyFixture };
