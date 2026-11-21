import type { VehicleCommand, VehicleInputLease } from "./vehiclePilot";

export const worldService = "http://127.0.0.1:8849";
export type XYZ = [number, number, number];
export type WorldInfo = {
  bounds: [number, number, number, number];
  mapRevision: string;
  streetTiles?: { revision: string; spans: number[]; pixels: number } | null;
  searchRegions?: { name: string; points: XYZ[]; radius: number; driveEnabled?: boolean }[];
  tiles: { revision: string; width: number; height: number; tileSize: number };
  atlas: { visualTrace: XYZ[]; coverageRadius: number };
};
type SearchState = { phase: string; samples: number; tracking: boolean; detailWidth?: number };
export type Decision = VehicleCommand & {
  worldSearch?: SearchState;
  reason: string;
  sequence: number;
  stopIndex?: number;
  remaining: number | null;
  computeMs: number;
  pose: { eye: XYZ; heading: number; supports: number } | null;
  path?: XYZ[];
};

export async function worldRequest<T>(
  endpoint: string,
  signal: AbortSignal,
  json?: object,
  token?: string,
  jpeg?: Blob,
  sequence?: number,
  mediaTime?: number,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers["X-World-Session"] = token;
  if (sequence !== undefined) headers["X-Frame-Sequence"] = String(sequence);
  if (mediaTime !== undefined)
    headers["X-Frame-Media-Time"] = String(mediaTime);
  if (jpeg || json)
    headers["Content-Type"] = jpeg ? "image/jpeg" : "application/json";
  const res = await fetch(worldService + endpoint, {
    method: jpeg || json ? "POST" : "GET",
    headers,
    signal,
    body: jpeg ?? (json ? JSON.stringify(json) : undefined),
    cache: "no-store",
    credentials: "omit",
  });
  const value = await res.json();
  if (!res.ok) throw Error(value.error || "service_error");
  return value;
}

function xyz(point: unknown): point is XYZ {
  return (
    Array.isArray(point) && point.length === 3 && point.every(Number.isFinite)
  );
}

export function usableDecision(
  d: Decision,
  seq: number,
  captured: number,
  now: number,
): boolean {
  return (
    !!d &&
    d.sequence === seq &&
    Number.isSafeInteger(seq) &&
    now >= captured &&
    now - captured < 320 &&
    !!d.pose &&
    xyz(d.pose.eye) &&
    Number.isFinite(d.pose.heading) &&
    Number.isInteger(d.pose.supports) &&
    d.pose.supports >= 24 &&
    Number.isFinite(d.remaining) &&
    d.remaining! >= 0 &&
    Number.isFinite(d.steering) &&
    Math.abs(d.steering) <= 0.35 &&
    ((d.reason === "following" &&
      ["coast", "throttle", "brake"].includes(d.pedal)) ||
      (d.reason === "stopping" &&
        d.steering === 0 &&
        ["coast", "brake"].includes(d.pedal)))
  );
}

export function worldFrameSampler(video: HTMLVideoElement) {
  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 360;
  const ctx = canvas.getContext("2d", { alpha: false });
  if (!ctx || typeof video.requestVideoFrameCallback !== "function")
    throw Error("video_unsupported");
  return (signal: AbortSignal, lastSequence: number, detailed = false) => {
    if (signal.aborted) throw Error("stream_stopped");
    return new Promise<{
      seq: number;
      mediaTime: number;
      captured: number;
      blob: Promise<Blob>;
    }>((resolve, reject) => {
      const cleanup = () => {
        clearTimeout(timeout);
        signal.removeEventListener("abort", cancelled);
      };
      const cancelled = () => {
        video.cancelVideoFrameCallback(id);
        cleanup();
        reject(Error("stream_stopped"));
      };
      const timeout = setTimeout(() => {
        video.cancelVideoFrameCallback(id);
        cleanup();
        reject(Error("frame_timeout"));
      }, 3500);
      const id = video.requestVideoFrameCallback((now, meta) => {
        cleanup();
        if (
          signal.aborted ||
          document.hidden ||
          video.paused ||
          Math.abs(video.videoWidth / video.videoHeight - 16 / 9) > 0.012 ||
          !Number.isFinite(meta.presentationTime) ||
          meta.presentedFrames <= lastSequence
        ) {
          reject(Error("stream_geometry_or_clock"));
          return;
        }
        try {
          const width = detailed && video.videoWidth >= 1280
            ? (video.videoWidth >= 1920 ? 1920 : 1280) : 640;
          if (canvas.width !== width) {
            canvas.width = width;
            canvas.height = width * 9 / 16;
          }
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          const blob = new Promise<Blob>((accept, fail) =>
            canvas.toBlob(
              (b) => (b ? accept(b) : fail(Error("frame_encode"))),
              "image/jpeg",
              detailed ? 0.96 : 0.91,
            ),
          );
          const capture = (
            meta as VideoFrameCallbackMetadata & { captureTime?: number }
          ).captureTime;
          resolve({
            seq: meta.presentedFrames,
            mediaTime: meta.mediaTime,
            captured: Math.min(now, meta.presentationTime, capture ?? now),
            blob,
          });
        } catch (err) {
          reject(err);
        }
      });
      signal.addEventListener("abort", cancelled, { once: true });
    });
  };
}

type Probe = {
  worldSearch?: SearchState;
  pose: Decision["pose"];
  district: string | null;
  ambiguous: boolean;
};
function detailSampler() {
  let last = -Infinity;
  return (state?: SearchState) => {
    const now = performance.now();
    if (state?.phase !== "collecting_views" || !state.detailWidth || now - last < 650) return false;
    last = now;
    return true;
  };
}
export async function probeWorldPosition(
  video: HTMLVideoElement,
  signal: AbortSignal,
  acquireMs = 180000,
  progress?: (frames: number, secondsLeft: number, phase?: string) => void,
) {
  const sample = worldFrameSampler(video);
  const detail = detailSampler();
  let searchState: SearchState | undefined;
  const timeout = AbortSignal.timeout(acquireMs);
  const search = AbortSignal.any([signal, timeout]);
  const deadline = performance.now() + acquireMs;
  let previous: Probe | null = null;
  let previousTime = -Infinity;
  let lastSequence = -1;
  let count = 0;
  let lastUpdate = -Infinity;
  try {
    while (!search.aborted) {
      const frame = await sample(search, lastSequence, detail(searchState)).catch((error: unknown) => {
        if (!search.aborted && error instanceof Error && error.message === "frame_timeout") return null;
        throw error;
      });
      if (!frame) { previous = null; continue; }
      lastSequence = frame.seq;
      const jpeg = await frame.blob;
      if (performance.now() - frame.captured >= 320) {
        previous = null;
        continue;
      }
      const result = await worldRequest<Probe>(
        "/probe",
        AbortSignal.any([search, AbortSignal.timeout(3500)]),
        undefined,
        undefined,
        jpeg,
      );
      if (search.aborted) break;
      searchState = result.worldSearch;
      const now = performance.now();
      count++;
      const pose = result.pose;
      if (
        now - frame.captured > 800 ||
        result.ambiguous ||
        !pose ||
        !xyz(pose.eye) ||
        !Number.isFinite(pose.heading) ||
        !Number.isInteger(pose.supports) ||
        pose.supports < 24
      ) {
        previous = null;
      } else {
        const age = frame.mediaTime - previousTime;
        if (
          previous?.pose &&
          age > 0 &&
          age <= 1.2 &&
          previous.district === result.district &&
          Math.hypot(...previous.pose.eye.map((v, j) => v - pose.eye[j])) <=
            3 &&
          Math.cos(previous.pose.heading - pose.heading) >= 0.97
        ) {
          return {
            eye: pose.eye,
            district: result.district,
            supports: pose.supports,
          };
        }
        previous = result;
        previousTime = frame.mediaTime;
      }
      if (now - lastUpdate >= 1000) {
        progress?.(count, Math.max(0, Math.ceil((deadline - now) / 1000)), result.worldSearch?.phase);
        lastUpdate = now;
      }
    }
  } catch (error) {
    if (!timeout.aborted || signal.aborted) throw error;
  }
  throw Error(signal.aborted ? "stream_stopped" : "position_timeout");
}

export async function runWorldTrip(
  video: HTMLVideoElement,
  token: string,
  signal: AbortSignal,
  openInput: () => Promise<VehicleInputLease>,
  update: (result: Decision, age: number) => void,
  acquireMs = 180000,
) {
  let lastFix = performance.now();
  const sample = worldFrameSampler(video);
  const detail = detailSampler();
  let searchState: SearchState | undefined;
  let lease: VehicleInputLease | undefined;
  let commanded = false;
  let strokes = 0;
  let nextLook = performance.now() + 2200;
  let lastSequence = -1;
  try {
    while (!signal.aborted) {
      if (performance.now() - lastFix >= acquireMs)
        throw Error("position_timeout");
      const frame = await sample(signal, lastSequence, detail(searchState));
      lastSequence = frame.seq;
      const jpeg = await frame.blob;
      if (signal.aborted) break;
      if (performance.now() - frame.captured >= 320) {
        lease?.neutral?.();
        continue;
      }
      const d = await worldRequest<Decision>(
        "/frame",
        AbortSignal.any([signal, AbortSignal.timeout(4000)]),
        undefined,
        token,
        jpeg,
        frame.seq,
        frame.mediaTime,
      );
      if (signal.aborted) break;
      if (d.sequence !== frame.seq) throw Error("frame_sequence");
      searchState = d.worldSearch;
      update(d, Math.round(performance.now() - frame.captured));
      if (d.reason === "arrived" || d.reason === "no_motion") return;
      if (lease && (!lease.active() || lease.failure?.()))
        throw Error("input_closed");
      // Stationary visual search uses the calibrated camera control of this trip.
      // Finish the symmetric sweep before allowing the first pedal command.
      const nowForLook = performance.now();
      const collecting = !d.pose && d.reason === "position_unknown" && d.worldSearch?.phase === "collecting_views";
      if (!commanded && strokes < 36 && (strokes > 0 || collecting) && nowForLook >= nextLook
          && nowForLook - frame.captured < 300) {
        lease ??= await openInput();
        if (signal.aborted || !lease.active() || lease.failure?.()) throw Error("input_closed");
        if (!lease.paused?.() && !lease.translating?.() && lease.look && lease.canLook?.()
            && performance.now() - frame.captured < 280) {
          const fraction = strokes < 9 || strokes >= 27 ? 0.038 : -0.038;
          if (await lease.look(fraction, frame.captured + 320)) {
            strokes++;
            nextLook = performance.now() + 500;
            continue;
          }
        }
        nextLook = performance.now() + 500;
      }
      if (strokes > 0 && strokes < 36) continue;
      if (!usableDecision(d, frame.seq, frame.captured, performance.now())) {
        lease?.neutral?.();
        continue;
      }
      lastFix = performance.now();
      if (!lease) lease = await openInput();
      if (signal.aborted || !lease.active() || lease.failure?.())
        throw Error("input_closed");
      const now = performance.now();
      if (
        lease.paused?.() ||
        !usableDecision(d, frame.seq, frame.captured, now)
      ) {
        lease.neutral?.();
        continue;
      }
      if (!lease.permit || !lease.neutral) throw Error("input_closed");
      lease.permit(frame.captured + 320);
      commanded = true;
      lease.setVehicle({
        pedal: d.pedal,
        steering: d.steering,
        ...(d.pedal === "throttle"
          ? { holdThrottle: true, throttlePulseMs: 180 as const }
          : {}),
      });
    }
  } finally {
    if (lease) {
      try {
        lease.neutral?.();
      } finally {
        await lease.close();
      }
    }
  }
}
