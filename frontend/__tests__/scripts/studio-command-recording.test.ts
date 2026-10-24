import { appendRecording, observeAcknowledgedRecording, recordedAction, recordingActions, type RecordedInput } from '@/src/features/scripts/studio/recording';
import type { AcknowledgedControl, StreamInput } from '@/src/features/stream/controlObservation';

let sequence = 0;
beforeEach(() => { sequence = 0; Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: () => `local-${++sequence}` }); });
const deviceId = 'owned-device';
function command(text = 'test input'): StreamInput { return { deviceId, at: 1000, dimensions: { width: 960, height: 540 }, command: { type: 'type_text', text } }; }
function event(input = command(), phase: AcknowledgedControl['phase'] = 'submitted', requestId = 'request-one'): AcknowledgedControl {
  return phase === 'submitted' ? { requestId, input, phase } : { requestId, input, phase, completedAt: 1800 };
}
function confirmed(input = command()): RecordedInput[] {
  return observeAcknowledgedRecording(observeAcknowledgedRecording([], event(input), deviceId, true), event(input, 'confirmed'), deviceId, false);
}

it('records submission before the response and requires an APK receipt before replay', () => {
  const pending = observeAcknowledgedRecording([], event(), deviceId, true);
  expect(pending[0].outcome).toBe('android-pending');
  expect(() => recordingActions(pending)).toThrow('нет подтверждённого');
  const done = observeAcknowledgedRecording(pending, event(command(), 'confirmed'), deviceId, false);
  expect(done[0]).toMatchObject({ at: 1000, completedAt: 1800, outcome: 'android-confirmed' });
  expect(recordingActions(done)).toEqual([{ type: 'type_text', text: 'test input', clear_first: false }]);
  expect(pending[0].outcome).toBe('android-pending');
});
it('keeps response order independent of submission order and avoids encoding round-trip delay twice', () => {
  const pending = observeAcknowledgedRecording([], event(), deviceId, true);
  const tap = { ...command(), at: 2000, command: { type: 'click' as const, x: 480, y: 270 } };
  const withTap = appendRecording(pending, tap, deviceId);
  const done = observeAcknowledgedRecording(withTap, event(command(), 'confirmed'), deviceId, false);
  expect(done.map(entry => entry.at)).toEqual([1000, 2000]);
  expect(recordingActions(done)).toEqual([{ type: 'type_text', text: 'test input', clear_first: false }, { type: 'sleep', ms: 200 }, { type: 'tap', x: 640, y: 360 }]);
});
it('does not append commands submitted outside recording or late results after explicit clear', () => {
  expect(observeAcknowledgedRecording([], event(), deviceId, false)).toEqual([]);
  expect(observeAcknowledgedRecording([], event(command(), 'confirmed'), deviceId, true)).toEqual([]);
});
it.each(['confirmed', 'unknown'] as const)('isolates foreign and mismatched %s receipts', phase => {
  const pending = observeAcknowledgedRecording([], event(), deviceId, true);
  for (const reply of [event(command(), phase, 'foreign-request'), event({ ...command(), deviceId: 'foreign-device' }, phase),
    event(command('different text'), phase), event({ ...command(), at: 1100 }, phase), event({ ...command(), dimensions: { width: 540, height: 960 } }, phase)]) {
    expect(observeAcknowledgedRecording(pending, reply, deviceId, false)).toBe(pending);
  }
});
it('does not turn an unknown result into confirmed execution after a duplicate reply', () => {
  const pending = observeAcknowledgedRecording([], event(), deviceId, true);
  const unknown = observeAcknowledgedRecording(pending, event(command(), 'unknown'), deviceId, false);
  expect(() => recordingActions(unknown)).toThrow('нет подтверждённого');
  expect(observeAcknowledgedRecording(unknown, event(command(), 'confirmed'), deviceId, false)).toBe(unknown);
});
it('ignores duplicate submissions and copies text/frame metadata', () => {
  const input = command(); const pending = observeAcknowledgedRecording([], event(input), deviceId, true);
  expect(observeAcknowledgedRecording(pending, event(input), deviceId, true)).toBe(pending);
  input.dimensions.width = 1; input.command = { type: 'type_text', text: 'rewritten' };
  expect(pending[0].command).toEqual({ type: 'type_text', text: 'test input' });
  expect(pending[0].dimensions.width).toBe(960);
});
it.each([3, 4, 187, 82, 67, 112, 66, 61, 278, 277, 279])('replays the actual Android keycode %s without inventing a gesture or buffer value', keycode => {
  const input = { ...command(), command: { type: 'key_event' as const, keycode } };
  expect(recordedAction(confirmed(input)[0])).toEqual({ type: 'key_event', keycode });
  expect(() => recordedAction(appendRecording([], input, deviceId)[0])).toThrow('не подтверждена');
});
it.each(['Привет', 'emoji🙂', 'two\nlines', 'literal%s', "apostrophe'", 'x'.repeat(1025)])('rejects text that the installed live input channel cannot reproduce', text => {
  expect(() => observeAcknowledgedRecording([], event(command(text)), deviceId, true)).toThrow('Текст не поддерживается');
});
it('applies the same 200-entry bound to text and navigation', () => {
  const entries = Array.from({ length: 200 }, (_, index) => ({ ...confirmed()[0], requestId: `old-${index}`, id: `old-${index}` }));
  expect(() => observeAcknowledgedRecording(entries, event(), deviceId, true)).toThrow('200');
  expect(entries).toHaveLength(200);
});
it('ignores impossible completion timestamps', () => {
  const pending = observeAcknowledgedRecording([], event(), deviceId, true);
  for (const completedAt of [999, NaN, Infinity]) expect(observeAcknowledgedRecording(pending, { ...event(), phase: 'confirmed', completedAt }, deviceId, false)).toBe(pending);
});
