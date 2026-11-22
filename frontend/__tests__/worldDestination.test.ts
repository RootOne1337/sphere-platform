import {probeWorldPosition, usableDecision, type Decision} from '../src/features/stream/worldDestination';

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
    { drawImage: jest.fn() } as unknown as CanvasRenderingContext2D,
  );
  const encode = jest.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(
    function (this: HTMLCanvasElement, done) { widths.push(this.width); done(new Blob(["jpeg"])); },
  );
  const prevFetch = globalThis.fetch;
  let moved = false;
  const close = jest.fn(async () => true);
  const set = jest.fn();
  const look = jest.fn(async () => { moved = true; return true; });
  globalThis.fetch = jest.fn(async () => ({ ok: true, json: async () => ({
    pose: moved ? good.pose : null, district: "Проверка", ambiguous: false,
    worldSearch: { phase: "collecting_views", samples: 1, tracking: false, detailWidth: 1920 },
  }) } as Response));
  try {
    const running = probeWorldPosition(video, new AbortController().signal, 10000,
      undefined, async () => ({ active: () => true, canLook: () => true, look, set, close }), {phase:"collecting_views", samples:0, tracking:false, detailWidth:1920});
    await jest.advanceTimersByTimeAsync(3500);
    await expect(running).resolves.toMatchObject({ supports: 37 });
    expect(look).toHaveBeenCalledTimes(1);
    expect(look).toHaveBeenCalledWith(0.16, expect.any(Number));
    expect(set).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledTimes(1);
    expect(widths).toContain(1920);
  } finally {
    jest.useRealTimers();
    context.mockRestore();
    encode.mockRestore();
    globalThis.fetch = prevFetch;
  }
});
