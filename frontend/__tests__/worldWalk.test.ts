import { worldWalkVector } from "../src/features/stream/worldWalk";

const decision = {
  sequence: 7, reason: "walking", remaining: 8, computeMs: 34,
  stick: [0, -0.32] as [number, number], lookRadians: 0,
  pose: { eye: [20, -5, 2] as [number, number, number], heading: 1, supports: 28 },
};

test("only a current geometrically supported walking correction can reach the stick", () => {
  expect(worldWalkVector(decision)).toEqual([0, -0.32]);
  for (const invalid of [
    { pose: null }, { pose: { ...decision.pose, supports: 23 } },
    { pose: { ...decision.pose, heading: Infinity } },
    { reason: "walk_aligning" }, { reason: "planning_walk" },
    { stick: [0.35, 0.35] as [number, number] },
  ]) {
    expect(worldWalkVector({ ...decision, ...invalid })).toBeNull();
  }
});
