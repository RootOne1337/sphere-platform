import assert from 'node:assert/strict';
import {readFileSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {createPlanner} from './world_grid.mjs';
import {createLanePlanner} from './lane_preview.mjs';

const [directory] = process.argv.slice(2);
if (!directory) throw new Error('usage: verify_ariane_surfaces.mjs <artifact-directory>');
const read = name => JSON.parse(readFileSync(join(directory, name), 'utf8'));
const drive = read('ariane-kremlin-surface.json');
const lanes = read('ariane-kremlin-lanes.json');
const walk = read('ariane-kremlin-footways-surface.json');
const footways = read('ariane-kremlin-footways-grid.json');

const lanePlanner = createLanePlanner(drive, lanes);
const laneExamples = lanes.lanes.map(lane => {
  const inset = Math.floor((lane.points.length - 1) / 12);
  return [lane.points[inset], lane.points.at(-1 - inset)];
});
assert.equal(laneExamples.length, 2);
const measured = laneExamples.map(([start, goal]) => {
  const result = lanePlanner.plan(start, goal);
  const reverse = lanePlanner.plan(goal, start);
  assert.equal(result.status, 'preview');
  assert.equal(result.executionQualified, false);
  assert.deepEqual(reverse.points, result.points.toReversed());
  return {laneId: result.laneId, length: result.length, points: result.points.length};
});
assert.equal(lanePlanner.plan(laneExamples[0][0], laneExamples[1][1]).reason, 'no_verified_lane_connection');
assert.equal(lanePlanner.plan(laneExamples[0][0], [2101.36, 2104.91]).reason, 'goal');

const walkPlanner = createPlanner(walk);
const pedestrian = walkPlanner.plan(...footways.example);
assert.equal(pedestrian.status, 'preview', JSON.stringify(pedestrian));
assert.equal(pedestrian.mode, 'walk');
assert.ok(pedestrian.length > 90 && pedestrian.points.length > 100);
const otherHeight = [...footways.example[0], pedestrian.start.xyz[2] + 8];
assert.equal(walkPlanner.plan(otherHeight, footways.example[1]).reason, 'start');
const result = {
  scope: 'offline geometry and routing preview',
  lanes: measured,
  pedestrian: {
    length: pedestrian.length,
    points: pedestrian.points.length,
    minClearance: pedestrian.minClearance,
    start: pedestrian.start.xyz,
    goal: pedestrian.goal.xyz,
  },
  rejected: ['cross-lane', 'unmapped-district', 'other-height'],
};
writeFileSync(join(directory, 'ariane-map-surface-acceptance.json'), JSON.stringify(result, null, 2) + '\n');
console.log(result);
