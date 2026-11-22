import { walkDecisionDeadline, type WalkInputLease } from "./walkPilot";
import { worldFrameSampler, worldRequest, type Decision } from "./worldDestination";

type WalkDecision = Omit<Decision, "pedal" | "steering"> & {
  stick: [number, number];
  lookRadians: number;
};

const terminal = new Set([
  "arrived", "no_motion", "menu_backdrop", "walk_path_unavailable",
  "walk_start_not_on_pavement",
]);

export function worldWalkVector(decision: WalkDecision): [number, number] | null {
  const pose = decision.pose;
  if (!pose || pose.supports < 24 || !Number.isFinite(pose.heading)
      || !pose.eye.every(Number.isFinite) || decision.reason !== "walking"
      || !Array.isArray(decision.stick) || decision.stick.length !== 2
      || !decision.stick.every(Number.isFinite) || Math.hypot(...decision.stick) > 0.350001)
    return null;
  return decision.stick;
}

export async function runWorldWalk(
  video: HTMLVideoElement,
  session: string,
  signal: AbortSignal,
  openInput: () => Promise<WalkInputLease>,
  update: (decision: Decision, age: number, commandAge?: number) => void,
  reacquire: () => Promise<void>,
  waitingForVideo?: () => void,
) {
  const sample = worldFrameSampler(video);
  let sequence = -1;
  let lease: WalkInputLease | undefined;
  let missingSince = performance.now();
  let nextLook = 0;
  try {
    while (!signal.aborted) {
      const frame = await sample(signal, sequence);
      if (!frame) {
        waitingForVideo?.();
        lease?.neutral?.();
        const released = await lease?.close();
        lease = undefined;
        if (released === false && !signal.aborted) throw Error("input_closed");
        continue;
      }
      sequence = frame.seq;
      const jpeg = await frame.blob;
      if (signal.aborted) break;
      if (performance.now() - frame.captured >= 250) {
        lease?.neutral?.();
        continue;
      }
      const result = await worldRequest<WalkDecision>(
        "/frame", AbortSignal.any([signal, AbortSignal.timeout(4000)]),
        undefined, session, jpeg, sequence, frame.mediaTime,
      );
      if (signal.aborted) break;
      if (result.sequence !== sequence) throw Error("frame_sequence");
      const now = performance.now();
      const age = Math.round(now - frame.captured);
      const decision: Decision = { ...result, pedal: "coast", steering: 0 };
      if (terminal.has(result.reason)) {
        update(decision, age);
        return;
      }
      const pose = result.pose;
      const verified = !!pose && pose.supports >= 24 && Number.isFinite(pose.heading)
        && pose.eye.every(Number.isFinite);
      if (verified) missingSince = now;
      else if (now - missingSince >= 6500) {
        lease?.neutral?.();
        await lease?.close();
        lease = undefined;
        await reacquire();
        missingSince = performance.now();
        continue;
      }
      const stick = worldWalkVector(result);
      const turn = verified && result.reason === "walk_aligning"
        && Number.isFinite(result.lookRadians) && now >= nextLook;
      if ((!stick && !turn) || age >= 250) {
        lease?.neutral?.();
        update(decision, age);
        continue;
      }
      lease ??= await openInput();
      if (signal.aborted) break;
      if (!lease.active() || lease.failure?.() || !lease.permit || !lease.neutral)
        throw Error("input_closed");
      const at = performance.now();
      const deadline = walkDecisionDeadline(frame.captured, at);
      if (!deadline || lease.paused?.() || document.hidden) {
        lease.neutral();
        update(decision, age);
        continue;
      }
      if (stick) {
        lease.permit(deadline);
        lease.set(stick);
        update(decision, age, Math.round(at - frame.captured));
      } else {
        lease.neutral();
        if (!lease.look || !lease.canLook) throw Error("world_camera_unavailable");
        if (lease.canLook()) {
          const fraction = -Math.sign(result.lookRadians) *
            Math.min(0.04, Math.max(0.024, Math.abs(result.lookRadians) / 5));
          if (await lease.look(fraction, Math.min(deadline, at + 220))) {
            nextLook = performance.now() + 180;
            update(decision, age, Math.round(at - frame.captured));
            continue;
          }
        }
        update(decision, age);
      }
    }
  } finally {
    lease?.neutral?.();
    await lease?.close();
  }
}
