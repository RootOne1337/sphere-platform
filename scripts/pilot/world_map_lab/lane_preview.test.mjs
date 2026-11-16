import test from 'node:test';
import assert from 'node:assert/strict';
import {createLanePlanner} from './lane_preview.mjs';

const surface = {
  worldId: 'test-world', areaId: 'test-district', mapRevision: 'revision-1',
  sources: {orthomapSha256: 'image-1'}, minClearance: 1,
};
const asset = {
  schema: 'sphere.lane-preview.v1',
  worldId: surface.worldId, areaId: surface.areaId, mapRevision: surface.mapRevision,
  orthomapSha256: surface.sources.orthomapSha256,
  separators: [0, 4, 8].map(x => ({ends: [[x, 0], [x + 1, 10]]})),
  lanes: [
    {id: 'left', direction: 'unverified', min_static_clearance_units: 1.5,
      points: [[2, 0, 10], [2.6, 6, 10.6], [3, 10, 11]]},
    {id: 'right', direction: 'unverified', min_static_clearance_units: 1.5,
      points: [[6, 0, 10], [6.6, 6, 10.6], [7, 10, 11]]},
  ],
};

test('binds A and B to the measured lane center at their respective heights', () => {
  const {plan} = createLanePlanner(surface, asset);
  const result = plan([2, 1, 10.1], [2.5, 8]);
  assert.equal(result.status, 'preview');
  assert.equal(result.executionQualified, false);
  assert.equal(result.direction, 'unverified');
  assert.equal(result.length > 7 && result.length < 7.1, true);
  assert.deepEqual(result.points, [[2.1, 1, 10.1], [2.6, 6, 10.6], [2.8, 8, 10.8]]);
  assert.deepEqual(plan([2.5, 8], [2, 1]).points, result.points.toReversed());
});

test('rejects an unknown connection, another level, the paint and unmeasured coordinates', () => {
  const {plan, snap} = createLanePlanner(surface, asset);
  assert.equal(plan([2, 1], [6, 8]).reason, 'no_verified_lane_connection');
  assert.equal(plan([2, 1, 7], [2.5, 8]).reason, 'start');
  assert.equal(plan([2, 1], [2.5, 11]).reason, 'goal');
  assert.equal(snap([4.1, 1]), null);
  assert.equal(snap([8.6, 1]), null);
});

test('rejects another source image and an under-clearance centerline', () => {
  assert.throws(() => createLanePlanner(surface, {...asset, orthomapSha256: 'other'}), /revision/);
  const bad = structuredClone(asset);
  bad.lanes[0].points[1][0] = 1;
  assert.throws(() => createLanePlanner(surface, bad), /centerline/);
});
