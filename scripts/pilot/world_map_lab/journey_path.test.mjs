import test from "node:test";
import assert from "node:assert/strict";
import { Itinerary } from "./journey_path.mjs";

test("short segments and mode changes preserve position and stop for transfers", () => {
  const plan = new Itinerary({
    legs: [
      {
        mode: "walk",
        path: [
          [0, 0, 0],
          [0.2, 0, 0],
          [0.2, 0, 0],
        ],
      },
      {
        mode: "drive",
        path: [
          [0.2, 0, 0],
          [20, 0, 0],
          [20, 17, 0],
        ],
      },
      {
        mode: "walk",
        path: [
          [20, 17, 0],
          [20, 17.3, 0],
        ],
      },
    ],
  });
  assert.ok(plan.duration > 0 && plan.duration < 60);
  for (const [idx, leg] of plan.legs.entries()) {
    assert.deepEqual(plan.sample(leg.start).p, leg.points[0]);
    assert.ok(Math.abs(plan.sample(leg.end).speed) < 1e-7);
    if (idx < 2) assert.ok(plan.sample(leg.end + 0.7).transfer);
  }
  const last = plan.sample(plan.duration);
  assert.ok(last.done);
  assert.deepEqual(last.p, [20, 17.3, 0]);
  assert.ok(!last.mounted);
  for (let t = 0; t < plan.duration; t += 0.2)
    assert.ok(plan.sample(t).camera.every(Number.isFinite));
});
test("a stationary recording cannot be played as a journey", () => {
  assert.throws(
    () =>
      new Itinerary({
        legs: [
          {
            mode: "walk",
            path: [
              [1, 1, 1],
              [1, 1, 1],
            ],
          },
        ],
      }),
  );
});

import { integrateVehicle } from "./journey_vehicle.mjs";
test("steering at rest and acceleration are consistent across render rates", () => {
  const profile = { wheelbase: 1.35 };
  const initial = { speed: 0, steer: 0, lean: 0 };
  assert.equal(
    integrateVehicle(
      initial,
      { axis: 0, turn: 1, grade: 0 },
      profile,
      "faggio",
      0.05,
    ).turn,
    0,
  );
  const drive = (fps) => {
    let state = initial;
    for (let i = 0; i < fps * 2; i++)
      state = integrateVehicle(
        state,
        { axis: 1, turn: 0.2, grade: 0 },
        profile,
        "faggio",
        1 / fps,
      );
    return state;
  };
  assert.ok(Math.abs(drive(30).speed - drive(120).speed) < 0.04);
  assert.ok(drive(30).speed > 5 && drive(30).lean > 0);
});
