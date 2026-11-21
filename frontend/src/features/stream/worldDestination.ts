import type { VehicleCommand, VehicleInputLease } from "./vehiclePilot";

export const worldService = "http://127.0.0.1:8849";
export type XYZ = [number, number, number];
export type WorldInfo = {
  bounds: [number, number, number, number];
  mapRevision: string;
  searchRegions?: { name: string; points: XYZ[]; radius: number }[];
  tiles: { revision: string; width: number; height: number; tileSize: number };
  atlas: { visualTrace: XYZ[]; coverageRadius: number };
};
export type Decision = VehicleCommand & {
  reason: string;
  sequence: number;
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
  return (signal: AbortSignal, lastSequence: number) => {
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
      const timeout = setTimeout(cancelled, 3500);
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
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          const blob = new Promise<Blob>((accept, fail) =>
            canvas.toBlob(
              (b) => (b ? accept(b) : fail(Error("frame_encode"))),
              "image/jpeg",
              0.91,
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
  pose: Decision["pose"];
  district: string | null;
  ambiguous: boolean;
};
export async function probeWorldPosition(
  video: HTMLVideoElement,
  signal: AbortSignal,
) {
  const sample = worldFrameSampler(video);
  let previous: Probe | null = null;
  let lastSequence = -1;
  for (let i = 0; i < 2; i++) {
    const frame = await sample(signal, lastSequence);
    lastSequence = frame.seq;
    const jpeg = await frame.blob;
    if (signal.aborted || performance.now() - frame.captured >= 320)
      throw Error("frame_stale");
    const result = await worldRequest<Probe>(
      "/probe",
      AbortSignal.any([signal, AbortSignal.timeout(3500)]),
      undefined,
      undefined,
      jpeg,
    );
    if (performance.now() - frame.captured > 800) throw Error("frame_stale");
    if (
      !result.pose ||
      !xyz(result.pose.eye) ||
      !Number.isFinite(result.pose.heading) ||
      result.pose.supports < 24
    )
      throw Error(result.ambiguous ? "ambiguous_position" : "position_unknown");
    if (previous?.pose) {
      const { eye, heading } = previous.pose;
      if (
        previous.district !== result.district ||
        Math.hypot(...eye.map((v, j) => v - result.pose!.eye[j])) > 3 ||
        Math.cos(heading - result.pose.heading) < 0.97
      )
        throw Error("ambiguous_position");
      return {
        eye: result.pose.eye,
        district: result.district,
        supports: result.pose.supports,
      };
    }
    previous = result;
  }
  throw Error("position_unknown");
}

export async function runWorldTrip(
  video: HTMLVideoElement,
  token: string,
  signal: AbortSignal,
  openInput: () => Promise<VehicleInputLease>,
  update: (result: Decision, age: number) => void,
) {
  const sample = worldFrameSampler(video);
  let lease: VehicleInputLease | undefined;
  let lastSequence = -1;
  try {
    while (!signal.aborted) {
      const frame = await sample(signal, lastSequence);
      lastSequence = frame.seq;
      const jpeg = await frame.blob;
      if (signal.aborted) break;
      if (performance.now() - frame.captured >= 320) {
        lease?.neutral?.();
        throw Error("frame_stale");
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
      update(d, Math.round(performance.now() - frame.captured));
      if (d.reason === "arrived" || d.reason === "no_motion") return;
      if (lease && (!lease.active() || lease.failure?.()))
        throw Error("input_closed");
      if (!usableDecision(d, frame.seq, frame.captured, performance.now())) {
        lease?.neutral?.();
        continue;
      }
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
