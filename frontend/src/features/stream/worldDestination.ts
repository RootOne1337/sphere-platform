import type { WalkInputLease } from "./walkPilot";
import type { VehicleCommand, VehicleInputLease } from "./vehiclePilot";

export const worldService = "http://127.0.0.1:8849";
export type XYZ = [number, number, number];
export type WorldInfo = {
  bounds: [number, number, number, number];
  mapRevision: string;
  walkAutopilot?: boolean;
  streetTiles?: { revision: string; spans: number[]; pixels: number } | null;
  worldSearch?: SearchState | null;
  searchRegions?: { name: string; points: XYZ[]; radius: number; driveEnabled?: boolean }[];
  tiles: { revision: string; width: number; height: number; tileSize: number };
  atlas: { visualTrace: XYZ[]; coverageRadius: number };
};
type SearchState = {
  phase: string;
  computePhase?: string;
  samples: number;
  tracking: boolean;
  detailWidth?: number;
};
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

type ProbeProgress = {
  frames: number;
  secondsLeft: number;
  phase?: string;
  cameraSteps: number;
  cameraTurns: number;
  cameraIssue?: string;
};
export type StartLevels = { drive: number | null; walk: number | null };

function agreedStartLevels(a?: Partial<StartLevels>, b?: Partial<StartLevels>): StartLevels {
  const level = (mode: keyof StartLevels) => {
    const previous = a?.[mode], current = b?.[mode];
    return typeof previous === "number" && Number.isFinite(previous) &&
      typeof current === "number" && Number.isFinite(current) && Math.abs(previous - current) <= 0.2
      ? current : null;
  };
  return { drive: level("drive"), walk: level("walk") };
}

type Probe = {
  screen?: "menu_backdrop";
  startLevels?: StartLevels;
  worldSearch?: SearchState;
  pose: Decision["pose"];
  district: string | null;
  ambiguous: boolean;
};
function detailSampler(allowWhileSearching = false) {
  let last = -Infinity;
  return (state?: SearchState) => {
    const now = performance.now();
    if (!state?.detailWidth || now - last < 650 || state.phase === "tracking" ||
      (!allowWhileSearching && state.phase !== "collecting_views")) return false;
    last = now;
    return true;
  };
}

function cameraViewSampler(video: HTMLVideoElement) {
  const canvas = document.createElement("canvas");
  canvas.width = 48;
  canvas.height = 48;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  return () => {
    if (!context || !video.videoWidth || !video.videoHeight) return null;
    context.drawImage(video, 0, 0, 48, 48);
    const rgba = context.getImageData(0, 0, 48, 48).data;
    return Float32Array.from({ length: 48 * 48 }, (_, i) =>
      0.299 * rgba[4 * i] + 0.587 * rgba[4 * i + 1] + 0.114 * rgba[4 * i + 2],
    );
  };
}

export function cameraViewChanged(before: Float32Array, after: Float32Array) {
  const differences = before.map((value, index) => value - after[index]);
  const sorted = differences.slice().sort();
  const exposure = sorted[sorted.length >> 1];
  const columns = new Set<number>();
  let tiles = 0;
  for (let row = 2; row < 5; row++) {
    for (let column = 0; column < 6; column++) {
      let sum = 0;
      for (let y = row * 8; y < row * 8 + 8; y++) {
        for (let x = column * 8; x < column * 8 + 8; x++) {
          sum += Math.abs(differences[y * 48 + x] - exposure);
        }
      }
      if (sum / 64 >= 6) {
        tiles++;
        columns.add(column);
      }
    }
  }
  return tiles >= 7 && columns.size >= 4;
}

export async function probeWorldPosition(
  video: HTMLVideoElement,
  signal: AbortSignal,
  acquireMs = 180000,
  progress?: (value: ProbeProgress) => void,
  openCamera?: (signal: AbortSignal) => Promise<WalkInputLease>,
  initialSearch?: SearchState | null,
  session?: string,
  walking = false,
) {
  const sample = worldFrameSampler(video);
  const detail = detailSampler(true);
  let searchState = initialSearch ?? undefined;
  const timeout = AbortSignal.timeout(acquireMs);
  const search = AbortSignal.any([signal, timeout]);
  const deadline = performance.now() + acquireMs;
  let previous: Probe | null = null;
  let previousTime = -Infinity;
  let lastSequence = -1;
  let count = 0;
  let lastUpdate = -Infinity;
  let camera: WalkInputLease | undefined;
  let cameraIssue: string | undefined;
  let cameraSteps = 0;
  let cameraTurns = 0;
  let stillStrokes = 0;
  let pendingView: Float32Array | null = null;
  const sampleView = cameraViewSampler(video);
  let nextStroke = performance.now() + 1400;
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
        walking ? "/walk-probe" : "/probe",
        AbortSignal.any([search, AbortSignal.timeout(3500)]),
        undefined,
        session,
        jpeg,
      );
      if (search.aborted) break;
      if (result.screen === "menu_backdrop") throw Error("menu_backdrop");
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
            startLevels: agreedStartLevels(previous.startLevels, result.startLevels),
          };
        }
        previous = result;
        previousTime = frame.mediaTime;
      }
      const phase = result.worldSearch?.phase;
      if (pendingView && now >= nextStroke) {
        const currentView = sampleView();
        if (currentView && cameraViewChanged(pendingView, currentView)) {
          cameraTurns++;
          stillStrokes = 0;
        } else if (currentView && ++stillStrokes >= 3) {
          cameraIssue = "world_camera_no_motion";
          await camera?.close();
          camera = undefined;
        }
        pendingView = null;
      }
      if (openCamera && !cameraIssue && !previous && !search.aborted &&
          cameraSteps < 12 && now >= nextStroke &&
          phase !== "tracking" && phase !== "verifying_geometry") {
        try {
          camera ??= await openCamera(search);
          if (search.aborted || !camera.active() || !camera.look) throw Error("world_camera_unavailable");
          if (camera.canLook?.() === true) {
            // Sweep one side and then cross the starting direction. The walking stick stays neutral.
            const fraction = cameraSteps < 3 || cameraSteps >= 9 ? 0.16 : -0.16;
            const before = sampleView();
            if (await camera.look(fraction, performance.now() + 240)) {
              cameraSteps++;
              pendingView = before;
            }
            nextStroke = performance.now() + 500;
          } else {
            nextStroke = performance.now() + 300;
          }
        } catch (error) {
          await camera?.close();
          camera = undefined;
          cameraIssue = error instanceof Error ? error.message : "world_camera_unavailable";
        }
      }
      if (now - lastUpdate >= 1000) {
        progress?.({ frames: count, secondsLeft: Math.max(0, Math.ceil((deadline - now) / 1000)),
          phase: result.worldSearch?.computePhase ?? phase,
          cameraSteps, cameraTurns, cameraIssue });
        lastUpdate = now;
      }
    }
  } catch (error) {
    if (!timeout.aborted || signal.aborted) throw error;
  } finally {
    await camera?.close();
  }
  throw Error(signal.aborted ? "stream_stopped" : cameraIssue ?? "position_timeout");
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
      if (d.reason === "arrived" || d.reason === "no_motion" || d.reason === "menu_backdrop") return;
      if (lease && (!lease.active() || lease.failure?.()))
        throw Error("input_closed");
      // Stationary visual search uses the calibrated camera control of this trip.
      // Finish the symmetric sweep before allowing the first pedal command.
      const nowForLook = performance.now();
      const collecting = !d.pose && d.reason === "position_unknown" && d.worldSearch?.phase === "collecting_views";
      if (!commanded && strokes < 36 && collecting && nowForLook >= nextLook
          && nowForLook - frame.captured < 300) {
        lease ??= await openInput();
        if (signal.aborted || !lease.active() || lease.failure?.()) throw Error("input_closed");
        if (!lease.paused?.() && !lease.translating?.() && lease.look && lease.canLook?.()
            && performance.now() - frame.captured < 280) {
          const fraction = strokes < 9 || strokes >= 27 ? 0.038 : -0.038;
          if (await lease.look(fraction, performance.now() + 240)) {
            strokes++;
            nextLook = performance.now() + 500;
            continue;
          }
        }
        nextLook = performance.now() + 500;
      }

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
