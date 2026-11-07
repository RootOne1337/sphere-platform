import { ServerLinkRtt } from '@/src/features/stream/serverLinkRtt';

let now = 0;
const setup = () => {
  const socket = { readyState: 1, bufferedAmount: 0, send: jest.fn() };
  return { socket, probe: new ServerLinkRtt(socket, () => now) };
};
beforeEach(() => { now = 0; });

test('one bounded echo is correlated and does not include clocks or Android input', () => {
  const { socket, probe } = setup();
  probe.tick(true); probe.tick(true);
  expect(socket.send).toHaveBeenCalledTimes(1);
  expect(JSON.parse(socket.send.mock.calls[0][0])).toEqual({ type: 'stream_link_probe', sequence: 1 });
  now = 24.5; probe.receive({ type: 'stream_link_result', sequence: 2 });
  expect(probe.sample()).toBeNull();
  probe.receive({ type: 'stream_link_result', sequence: 1 });
  expect(probe.sample()).toEqual({ rttMs: 24.5, ageMs: 0 });
  now = 124.5; expect(probe.sample()?.ageMs).toBe(100);
});
test('no reply clears the old measurement and late or duplicate replies do not update it', () => {
  const { socket, probe } = setup();
  probe.tick(true); now = 2; probe.receive({ type: 'stream_link_result', sequence: 1 });
  now = 5000; probe.tick(true);
  now = 10000; probe.tick(true);
  expect(probe.sample()).toBeNull();
  probe.receive({ type: 'stream_link_result', sequence: 2 });
  expect(probe.sample()).toBeNull();
  expect(socket.send).toHaveBeenCalledTimes(3);
});
test.each(['hidden', 'closed', 'backpressure', 'suspended', 'stopped', 'clock_reversed'])('%s discards a historic RTT', mode => {
  const { socket, probe } = setup();
  probe.tick(true); now = 1; probe.receive({ type: 'stream_link_result', sequence: 1 });
  if (mode === 'closed') socket.readyState = 3;
  if (mode === 'backpressure') socket.bufferedAmount = 65537;
  if (mode === 'suspended') now = 20000;
  if (mode === 'clock_reversed') now = -1;
  if (mode === 'stopped') probe.stop();
  probe.tick(mode !== 'hidden');
  expect(probe.sample()).toBeNull();
});
test('a late reply after a suspended page or a throwing send is not a zero RTT', () => {
  const { socket, probe } = setup();
  probe.tick(true); now = 10000;
  probe.receive({ type: 'stream_link_result', sequence: 1 });
  expect(probe.sample()).toBeNull();
  socket.send.mockImplementation(() => { throw new Error('closed'); });
  probe.tick(true); expect(probe.sample()).toBeNull();
});
