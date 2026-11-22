import {cameraViewChanged, probeWorldPosition, runWorldTrip, usableDecision, type Decision} from '../src/features/stream/worldDestination';
import {runWorldWalk} from '../src/features/stream/worldWalk';

const good:Decision={sequence:93,reason:'following',pedal:'throttle',steering:.1,remaining:14,computeMs:48,
  pose:{eye:[-15,24,9],heading:1,supports:37}};
test('only current geometric decisions authorize input',()=>{
  expect(usableDecision(good,93,200,380)).toBe(true);
  expect(usableDecision(good,92,200,380)).toBe(false);
  expect(usableDecision(good,93,200,520)).toBe(false);
  expect(usableDecision(good,93,200,190)).toBe(false);
  for(const change of [{pose:null},{steering:.36},{remaining:NaN},{reason:'confirming_position'},{reason:'stopping'},{reason:'arrived'}])
    expect(usableDecision({...good,...change},93,200,380)).toBe(false);
  expect(usableDecision({...good,reason:'stopping',steering:0,pedal:'brake'},93,200,380)).toBe(true);
});



test("position search turns a neutral camera, submits detail frames and closes the lease", async () => {
  jest.useFakeTimers();
  const video = document.createElement("video");
  let frame = 0;
  Object.defineProperties(video, {
    videoWidth: { value: 1920 },
    videoHeight: { value: 1080 },
    paused: { value: false },
    requestVideoFrameCallback: {
      value: (callback: VideoFrameRequestCallback) => setTimeout(() => {
        frame++;
        callback(performance.now(), { presentationTime: performance.now(),
          presentedFrames: frame, mediaTime: frame * 0.15 } as VideoFrameCallbackMetadata);
      }, 150),
    },
    cancelVideoFrameCallback: { value: clearTimeout },
  });
  const widths: number[] = [];
  const context = jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    { drawImage: jest.fn(), getImageData: () => ({data: new Uint8ClampedArray(48 * 48 * 4)}) } as unknown as CanvasRenderingContext2D,
  );
  const encode = jest.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(
    function (this: HTMLCanvasElement, done) { widths.push(this.width); done(new Blob(["jpeg"])); },
  );
  const prevFetch = globalThis.fetch;
  let moved = false, menu = false;
  const close = jest.fn(async () => true);
  const set = jest.fn();
  const look = jest.fn(async () => { moved = true; return true; });
  globalThis.fetch = jest.fn(async () => ({ ok: true, json: async () => ({
    pose: moved ? good.pose : null, district: "Проверка", ambiguous: false,
    screen: menu ? "menu_backdrop" : undefined,
    startLevels: { drive: 8 - frame % 2, walk: 7.5 },
    worldSearch: { phase: "collecting_views", samples: 1, tracking: false, detailWidth: 1920 },
  }) } as Response));
  try {
    const running = probeWorldPosition(video, new AbortController().signal, 10000,
      undefined, async () => ({ active: () => true, canLook: () => true, look, set, close }), {phase:"tracking", samples:0, tracking:true, detailWidth:1920});
    await jest.advanceTimersByTimeAsync(3500);
    await expect(running).resolves.toMatchObject({ supports: 37, startLevels: { drive: null, walk: 7.5 } });
    expect(look).toHaveBeenCalledTimes(1);
    expect(look).toHaveBeenCalledWith(0.16, expect.any(Number));
    expect(set).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledTimes(1);
    expect(widths[0]).toBe(1920);
    expect(widths).toContain(1920);
    menu = true;
    const open = jest.fn();
    const stopped = expect(probeWorldPosition(video, new AbortController().signal, 10000,
      undefined, open)).rejects.toThrow("menu_backdrop");
    await jest.advanceTimersByTimeAsync(500);
    await stopped;
    expect(open).not.toHaveBeenCalled();
  } finally {
    jest.useRealTimers();
    context.mockRestore();
    encode.mockRestore();
    globalThis.fetch = prevFetch;
  }
});

test.each(["walk", "drive"] as const)("%s releases input during a presentation gap and continues the same route", async mode => {
  jest.useFakeTimers();
  const video = document.createElement("video");
  let frame = 0;
  Object.defineProperties(video, {
    videoWidth: { value: 1920 },
    videoHeight: { value: 1080 },
    paused: { value: false },
    requestVideoFrameCallback: {
      value: (callback: VideoFrameRequestCallback) => setTimeout(() => {
        frame++;
        callback(performance.now(), {
          presentationTime: performance.now(), presentedFrames: frame, mediaTime: performance.now() / 1000,
        } as VideoFrameCallbackMetadata);
      }, performance.now() > 0 && performance.now() < 2900 ? 4000 : 100),
    },
    cancelVideoFrameCallback: { value: clearTimeout },
  });
  const context = jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    { drawImage: jest.fn() } as unknown as CanvasRenderingContext2D,
  );
  const encode = jest.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(
    done => done(new Blob(["jpeg"])),
  );
  const abort = new AbortController();
  const prevFetch = globalThis.fetch;
  const requests = jest.fn(async (_url: string, options: RequestInit) => {
    const seq = Number((options.headers as Record<string, string>)["X-Frame-Sequence"]);
    const reason = seq === 4 ? "arrived" : seq === 2 ? "confirming_position" : mode === "walk" ? "walking" : "following";
    return { ok: true, json: async () => ({ ...good, sequence: seq, reason, stick: [0, -0.2] }) } as Response;
  });
  globalThis.fetch = requests as unknown as typeof fetch;
  const close = jest.fn(async () => true);
  const neutral = jest.fn();
  const command = jest.fn();
  const input = jest.fn(async () => ({
    active: () => true, permit: jest.fn(), neutral, set: command, setVehicle: command, close,
  }));
  const waiting = jest.fn();
  try {
    const run = mode === "walk"
      ? runWorldWalk(video, "trip", abort.signal, input, jest.fn(), jest.fn(), waiting)
      : runWorldTrip(video, "trip", abort.signal, input, jest.fn(), 10000, waiting);
    await jest.advanceTimersByTimeAsync(2000);
    expect(command).toHaveBeenCalledTimes(1);
    expect(waiting).toHaveBeenCalledTimes(1);
    expect(neutral).toHaveBeenCalled();
    expect(close).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(2200);
    await run;
    expect(command).toHaveBeenCalledTimes(2);
    expect(input).toHaveBeenCalledTimes(2);
    expect(close).toHaveBeenCalledTimes(2);
    expect(requests.mock.calls.map(([, options]) => (options.headers as Record<string, string>)["X-World-Session"]))
      .toEqual(["trip", "trip", "trip", "trip"]);
  } finally {
    abort.abort();
    jest.useRealTimers();
    context.mockRestore();
    encode.mockRestore();
    globalThis.fetch = prevFetch;
  }
});

test("local animation and exposure do not count as a camera turn", () => {
  const before = Float32Array.from({length: 48 * 48}, (_, i) => 70 + (i % 56));
  const animation = before.map((v, i) => v + 12 + (i % 48 < 14 ? 40 : 0));
  const turn = before.map((v, i) => v + (16 <= (i / 48 | 0) && (i / 48 | 0) < 40 && i % 48 < 38 ? 45 : 0));
  expect(cameraViewChanged(before, animation)).toBe(false);
  expect(cameraViewChanged(before, turn)).toBe(true);
});
