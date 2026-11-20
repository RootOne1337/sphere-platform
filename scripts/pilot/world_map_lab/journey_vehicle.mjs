const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const move = (a, b, d) => a + clamp(b - a, -d, d);
export function integrateVehicle(state, input, profile, kind, dt) {
  // Wheel contacts and wheelbase are measured in the source model. Grip and engine
  // constants belong to the offline simulator and may be calibrated independently.
  const bike = kind === "faggio",
    g = 9.81,
    max = bike ? 24 : 32,
    accel = bike ? 4.1 : 4.8;
  const drag = 0.16 + 0.0018 * state.speed ** 2;
  const throttle = input.axis,
    braking = state.speed * throttle < -0.12;
  let speed = state.speed;
  if (braking) speed = move(speed, 0, 7.5 * dt);
  else if (throttle)
    speed +=
      dt *
      (throttle *
        accel *
        (1 - Math.min(1, Math.abs(speed) / (throttle > 0 ? max : 3.5))) -
        Math.sign(speed) * drag);
  else speed = move(speed, 0, drag * dt);
  if (throttle || Math.abs(speed) > 0.18)
    speed -= g * clamp(input.grade, -0.35, 0.35) * dt;
  speed = clamp(speed, -3.5, max);
  const steer = move(state.steer, input.turn * 0.55, dt * 1.65);
  const yawRate = clamp(
    (speed * Math.tan(steer)) / profile.wheelbase,
    -Math.min(1.6, 6 / Math.max(1, Math.abs(speed))),
    Math.min(1.6, 6 / Math.max(1, Math.abs(speed))),
  );
  const bank = bike ? Math.atan2(speed * yawRate, g) : 0;
  const lean = move(state.lean, bank, dt * 1.8);
  return { speed, steer, lean, turn: yawRate * dt };
}
