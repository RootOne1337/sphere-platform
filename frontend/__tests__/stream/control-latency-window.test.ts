import { ControlLatencyWindow } from '@/src/features/stream/controlLatencyWindow';

test('idle ACKs and invalid values do not invent an action latency', () => {
  const window = new ControlLatencyWindow();
  for (const ms of [-1, NaN, Infinity, 10_001]) window.record(1, ms);
  window.record(4, 300);
  expect(window.snapshot()).toBeNull();
});

test('an acknowledged click burst retains its peak across subsequent idle heartbeats', () => {
  const window = new ControlLatencyWindow();
  for (const ms of [2, 180, 12]) window.record(1, ms);
  for (let i = 0; i < 200; i++) window.record(4, 1);
  expect(window.snapshot()).toEqual({ samples: 3, p95Ms: 180, maxMs: 180 });
});

test('only the fixed last 128 actions influence the window after a long session', () => {
  const window = new ControlLatencyWindow();
  window.record(5, 9000);
  for (let ms = 0; ms < 128; ms++) window.record(1, ms);
  expect(window.snapshot()).toEqual({ samples: 128, p95Ms: 121, maxMs: 127 });
});
