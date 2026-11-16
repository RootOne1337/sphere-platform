import assert from 'node:assert/strict';
import test from 'node:test';

import {createPlanner} from './world_grid.mjs';

function tile(width, height, open, z = Array(open.length).fill(0)) {
  const heights = Buffer.alloc(z.length * 2);
  const clearance = Buffer.alloc(z.length * 2);
  for (let i = 0; i < z.length; i++) {
    heights.writeInt16LE(z[i] * 100, i * 2);
    clearance.writeUInt16LE(open[i] ? 150 : 0, i * 2);
  }
  return {
    schema: 'sphere.raster-surface.v1', worldId: 'test-world', areaId: 'test-area',
    mapRevision: 'a'.repeat(64), mode: 'walk', minClearance: 1.25, maxGrade: .4,
    grid: {width, height, step: 1, left: 0, top: height, baseZ: 420},
    free: Buffer.from(open).toString('base64'),
    clearanceCentiUnits: clearance.toString('base64'),
    heightCentiUnits: heights.toString('base64'),
  };
}

test('returns a version-bound 3D plan across an unrelated world', () => {
  const planner = createPlanner(tile(3, 2, [1, 1, 1, 1, 1, 1]));
  const plan = planner.plan([.5, 1.5, 420], [2.5, 1.5, 420]);
  assert.equal(plan.status, 'preview');
  assert.equal(plan.worldId, 'test-world');
  assert.equal(plan.mode, 'walk');
  assert.equal(plan.length, 2);
  assert.equal(plan.minClearance, 1.5);
  assert.deepEqual(plan.points, [[.5, 1.5, 420], [1.5, 1.5, 420], [2.5, 1.5, 420]]);
});

test('two touching corners cannot connect across blocked side cells', () => {
  const planner = createPlanner(tile(2, 2, [1, 0, 0, 1]));
  const plan = planner.plan([.5, 1.5], [1.5, .5]);
  assert.equal(plan.reason, 'disconnected');
});

test('an overpass height jump cannot be treated as a drivable connection', () => {
  const planner = createPlanner(tile(2, 1, [1, 1], [0, 4]));
  const plan = planner.plan([.5, .5, 420], [1.5, .5, 424]);
  assert.equal(plan.reason, 'disconnected');
  assert.equal(planner.snap([.5, .5, 422]), null);
});

test('rejects an off-map target even if a nearby road would fall within snap radius', () => {
  const planner = createPlanner(tile(3, 1, [1, 1, 1]));
  assert.equal(planner.plan([.5, .5], [3.1, .5]).reason, 'goal');
  assert.equal(planner.snap([Number.NaN, .5]), null);
});

test('fails closed on a truncated raster or unknown package version', () => {
  const valid = tile(2, 1, [1, 1]);
  assert.throws(() => createPlanner({...valid, heightCentiUnits: ''}), /surface stream length/);
  assert.throws(() => createPlanner({...valid, schema: 'unsupported'}), /surface identity/);
});
