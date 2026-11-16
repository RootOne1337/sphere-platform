import assert from 'node:assert/strict';
import fs from 'node:fs';
import {performance} from 'node:perf_hooks';
import {createPlanner} from './world_grid.mjs';

const [tileFile, reportFile] = process.argv.slice(2);
if (!tileFile || !reportFile) throw new Error('Use: node verify_ariane_routes.mjs <tile.json> <report.json>');
const tile = JSON.parse(fs.readFileSync(tileFile, 'utf8'));
const planner = createPlanner(tile);
const cellMask = Buffer.from(tile.free, 'base64');
const clearance = Buffer.from(tile.clearanceCentiUnits, 'base64');
const heights = Buffer.from(tile.heightCentiUnits, 'base64');
const {grid} = tile;
const cases = [
  ['south-to-north-via-east', [-2915, 2412], [-2867, 2645]],
  ['reverse', [-2867, 2645], [-2915, 2412]],
  ['riverfront', [-2915, 2390], [-2906, 2670]],
  ['around-block', [-2909, 2510], [-2873, 2480]],
  ['east-side', [-2874, 2478], [-2867, 2650]],
  ['alley-exit', [-2888, 2447.5], [-2913.75, 2390]],
  ['unlinked-strip', [-2968.75, 2450], [-2913.75, 2450], 'disconnected'],
  ['nonroad-goal', [-2910, 2500], [-2824, 2470], 'goal'],
  ['wrong-level', [-2915, 2412, 100], [-2867, 2645], 'start'],
  ['outside-tile', [-2971, 2350], [-2867, 2645], 'start'],
];

function checkCell(col, row) {
  assert.ok(col >= 0 && col < grid.width && row >= 0 && row < grid.height);
  const i = row * grid.width + col;
  const height = grid.baseZ + heights.readInt16LE(i * 2) / 100;
  const reserve = clearance.readUInt16LE(i * 2) / 100;
  assert.equal(cellMask[i], 1);
  assert.ok(reserve >= tile.minClearance);
  return {col, row, height, reserve};
}

function checkPath(plan) {
  let previous;
  let length = 0;
  let minClearance = Infinity;
  let checkedCells = 0;
  for (const [x, y, z] of plan.points) {
    const current = checkCell(Math.floor((x - grid.left) / grid.step), Math.floor((grid.top - y) / grid.step));
    assert.equal(z, current.height);
    minClearance = Math.min(minClearance, current.reserve);
    checkedCells++;
    if (previous) {
      const dx = Math.abs(current.col - previous.col);
      const dy = Math.abs(current.row - previous.row);
      const horizontal = Math.hypot(dx, dy) * grid.step;
      const climb = Math.abs(z - previous.height);
      assert.ok(dx <= 1 && dy <= 1 && horizontal > 0);
      assert.ok(climb <= horizontal * tile.maxGrade + .0100001);
      if (dx && dy) {
        const maximum = grid.step * tile.maxGrade + .0100001;
        for (const side of [checkCell(previous.col, current.row), checkCell(current.col, previous.row)]) {
          assert.ok(Math.abs(side.height - previous.height) <= maximum);
          assert.ok(Math.abs(side.height - z) <= maximum);
          checkedCells++;
        }
      }
      length += Math.hypot(horizontal, climb);
    }
    previous = current;
  }
  assert.equal(plan.minClearance, minClearance);
  assert.ok(Math.abs(length - plan.length) < 1e-9);
  assert.deepEqual(plan.points[0], plan.start.xyz);
  assert.deepEqual(plan.points.at(-1), plan.goal.xyz);
  return checkedCells;
}

const results = cases.map(([id, start, goal, reason]) => {
  const began = performance.now();
  const plan = planner.plan(start, goal);
  const ms = performance.now() - began;
  if (reason) {
    assert.equal(plan.status, 'unreachable', id);
    assert.equal(plan.reason, reason, id);
    return {id, start, goal, status: plan.status, reason, ms};
  }
  assert.equal(plan.status, 'preview', id);
  assert.equal(plan.mapRevision, tile.mapRevision);
  const checkedCells = checkPath(plan);
  return {id, start, goal, status: plan.status, length: plan.length, points: plan.points.length,
    minClearance: plan.minClearance, checkedCells, ms};
});

fs.writeFileSync(reportFile, JSON.stringify({
  scope: 'Static, single surface layer. No game input or measured live poses.',
  mapRevision: tile.mapRevision,
  results,
}, null, 2) + '\n', 'utf8');
console.table(results.map(({id, status, length, points, reason, ms}) =>
  ({id, status, length: length?.toFixed(2), points, reason, ms: ms.toFixed(1)})));
