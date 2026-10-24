import { act, fireEvent, render, screen } from '@testing-library/react';
import { api } from '@/lib/api';
import { AndroidNavigationBar } from '@/src/features/stream/AndroidNavigationBar';
import type { AcknowledgedControl } from '@/src/features/stream/controlObservation';
import { observeAcknowledgedRecording, recordingActions, type RecordedInput } from '@/src/features/scripts/studio/recording';

let mockToken = 'fixture';
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: mockToken }) }));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
beforeEach(() => { jest.clearAllMocks(); mockToken = 'fixture'; Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: () => 'request-fixture' }); });
function open(observer = jest.fn(), available = true) {
  return { observer, ...render(<AndroidNavigationBar deviceId="owned-device" available={available} isAvailable={() => available} extended
    getFrameDimensions={() => ({ width: 960, height: 540 })} onControlCommand={observer} />) };
}
it.each([['Назад', 4], ['Домой', 3], ['Недавние', 187], ['Меню', 82]] as const)(
  'records %s as the actual acknowledged Android key and exports it after Stop', async (label, keycode) => {
    let finish!: (value: unknown) => void;
    jest.mocked(api.post).mockReturnValue(new Promise(resolve => { finish = resolve; }) as never);
    let entries: RecordedInput[] = [], recording = true;
    open(jest.fn((event: AcknowledgedControl) => {
      entries = observeAcknowledgedRecording(entries, event, 'owned-device', recording);
    }));
    fireEvent.click(screen.getByRole('button', { name: label }));
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ outcome: 'android-pending', command: { type: 'key_event', keycode } });
    expect(() => recordingActions(entries)).toThrow('нет подтверждённого результата');
    recording = false;
    await act(async () => finish({ data: { output: '' } }));
    expect(entries).toHaveLength(1);
    expect(entries[0].outcome).toBe('android-confirmed');
    expect(recordingActions(entries)).toEqual([{ type: 'key_event', keycode }]);
    expect(api.post).toHaveBeenCalledTimes(1);
  },
);
it('observes the actual key before awaiting HTTP and then confirms the same request without changing its timestamp', async () => {
  let finish!: (value: unknown) => void;
  jest.mocked(api.post).mockReturnValue(new Promise(resolve => { finish = resolve; }) as never);
  const { observer } = open();
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  expect(observer).toHaveBeenCalledTimes(1);
  const submitted: AcknowledgedControl = observer.mock.calls[0][0];
  expect(submitted).toMatchObject({ requestId: 'request-fixture', phase: 'submitted', input: { deviceId: 'owned-device', dimensions: { width: 960, height: 540 }, command: { type: 'key_event', keycode: 4 } } });
  await act(async () => finish({ data: { output: '' } }));
  expect(observer.mock.calls[1][0]).toMatchObject({ requestId: submitted.requestId, phase: 'confirmed', input: submitted.input });
  expect(observer.mock.calls[1][0].completedAt).toBeGreaterThanOrEqual(submitted.input.at);
});
it.each([{ error: 'failure' }, { accepted: true }, null])('does not confirm malformed or error receipts %j', async data => {
  jest.mocked(api.post).mockResolvedValue({ data }); const { observer } = open();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Домой' })));
  expect(observer.mock.calls.map(([event]) => event.phase)).toEqual(['submitted', 'unknown']);
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('captures original text once, keeps it out of receipts and marks a timeout unknown without retry', async () => {
  jest.mocked(api.post).mockRejectedValue(new Error('timeout')); const { observer } = open();
  fireEvent.change(screen.getByLabelText('Текст для Android'), { target: { value: 'sample text' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Ввести текст' })));
  expect(observer.mock.calls[0][0].input.command).toEqual({ type: 'type_text', text: 'sample text' });
  expect(observer.mock.calls.map(([event]) => event.phase)).toEqual(['submitted', 'unknown']);
  expect(screen.getByRole('alert')).not.toHaveTextContent('sample text');
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('marks an interrupted wait unknown once and ignores its late success', async () => {
  let finish!: (value: unknown) => void;
  jest.mocked(api.post).mockReturnValue(new Promise(resolve => { finish = resolve; }) as never);
  const { observer, unmount } = open(); fireEvent.click(screen.getByRole('button', { name: 'Домой' })); unmount();
  await act(async () => finish({ data: { output: '' } }));
  expect(observer.mock.calls.map(([event]) => event.phase)).toEqual(['submitted', 'unknown']);
});
it('isolates observer failures and mutations from the delivered command and subsequent APK receipt', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { output: '' } });
  const events: AcknowledgedControl[] = [];
  open(jest.fn((event: AcknowledgedControl) => {
    events.push(event);
    if (event.phase === 'submitted') { event.input.command = { type: 'type_text', text: 'changed' }; throw new Error('local observer'); }
  }));
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Домой' })));
  expect(events[1].input.command).toEqual({ type: 'key_event', keycode: 3 });
  expect(screen.getByRole('status')).toHaveTextContent('выполнение подтверждено');
});
it('does not observe or send disabled controls', () => {
  const { observer } = open(jest.fn(), false);
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  expect(api.post).not.toHaveBeenCalled(); expect(observer).not.toHaveBeenCalled();
});
