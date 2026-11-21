const React = require('react');
const { act, fireEvent, render, screen } = require('@testing-library/react');

jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: 'fixture' }) }));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));

const { api } = require('@/lib/api');
const { AndroidNavigationBar } = require('@/src/features/stream/AndroidNavigationBar');
const { observeAcknowledgedRecording, recordingActions } = require('@/src/features/scripts/studio/recording');

beforeEach(() => {
  jest.clearAllMocks();
  let sequence = 0;
  Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: () => String(++sequence) });
});

it.each([
  { label: 'direct not_sent', useDirect: true, httpCalls: 0 },
  { label: 'shell device_input_busy', useDirect: false, httpCalls: 1 },
])('$label shows not sent but blocks Studio export', async ({ useDirect, httpCalls }) => {
  api.post.mockResolvedValue({ data: { error: 'device_input_busy' } });
  const direct = jest.fn().mockResolvedValue({ outcome: 'not_sent' });
  const finish = jest.fn();
  let entries = [];
  const phases = [];
  const deviceId = 'fixture-device';

  render(React.createElement(AndroidNavigationBar, {
    deviceId,
    available: true,
    isAvailable: () => true,
    sendDirectKey: useDirect ? direct : undefined,
    prepareCommand: () => finish,
    getFrameDimensions: () => ({ width: 960, height: 540 }),
    onControlCommand: event => {
      phases.push(event.phase);
      entries = observeAcknowledgedRecording(entries, event, deviceId, true);
    },
  }));

  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Домой' })));
  expect(screen.getByRole('alert')).toHaveTextContent('команда не отправлена');
  expect(phases).toEqual(['submitted', 'unknown']);
  expect(entries.map(entry => entry.outcome)).toEqual(['android-unknown']);
  expect(() => recordingActions(entries)).toThrow('нет подтверждённого результата');
  expect(api.post).toHaveBeenCalledTimes(httpCalls);
  expect(direct).toHaveBeenCalledTimes(useDirect ? 1 : 0);
  if (!useDirect) expect(finish).toHaveBeenCalledWith(true);
});
