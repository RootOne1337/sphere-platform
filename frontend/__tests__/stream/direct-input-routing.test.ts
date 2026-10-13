import { deferLegacyInput } from '@/src/features/stream/directInputRouting';

const shared = { admissionKnown: true, admitted: true, active: false, sharedInput: true };
const peer = { readyState: 1, sharedInput: true };

test('a history-aware viewer waits for admission before acquiring exclusive native input', () => {
  expect(deferLegacyInput(true, { ...shared, admissionKnown: false }, null)).toBe(true);
});

test('a shared viewer never starts a legacy owner during ICE setup or direct retry', () => {
  expect(deferLegacyInput(true, shared, null)).toBe(true);
  expect(deferLegacyInput(true, { ...shared, active: true }, null)).toBe(true);
  expect(deferLegacyInput(true, shared, peer)).toBe(true);
});

test('readiness requires the same active shared endpoint, not a stale or v1 channel', () => {
  expect(deferLegacyInput(true, { ...shared, active: true }, peer)).toBe(false);
  expect(deferLegacyInput(true, { ...shared, active: true }, { ...peer, readyState: 3 })).toBe(true);
  expect(deferLegacyInput(true, { ...shared, active: true }, { readyState: 1 })).toBe(true);
});

test('older agents, disabled direct mode and older servers keep their legacy path', () => {
  expect(deferLegacyInput(true, { ...shared, sharedInput: false }, null)).toBe(false);
  expect(deferLegacyInput(true, { ...shared, admitted: false }, null)).toBe(false);
  expect(deferLegacyInput(false, { ...shared, admissionKnown: false }, null)).toBe(false);
});
