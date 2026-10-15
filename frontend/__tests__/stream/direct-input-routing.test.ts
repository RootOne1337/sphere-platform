import { deferLegacyInput } from '@/src/features/stream/directInputRouting';

const shared = { admissionKnown: true, admitted: true, active: false, sharedInput: true };
const peer = { readyState: 1, sharedInput: true };

test('a history-aware viewer waits for admission before acquiring exclusive native input', () => {
  expect(deferLegacyInput(true, { ...shared, admissionKnown: false }, null)).toBe(true);
});

test('a shared viewer waits during its initial ICE setup', () => {
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

test('a retired direct failure permits fallback admission throughout background retries', () => {
  expect(deferLegacyInput(true, { ...shared, result: { state: 'failed' } }, null)).toBe(false);
  expect(deferLegacyInput(true, { ...shared, result: { state: 'stopped' } }, null)).toBe(false);
  expect(deferLegacyInput(true, { ...shared, result: { state: 'gathering' } }, null)).toBe(true);
  expect(deferLegacyInput(true, { ...shared, result: { state: 'connecting' } }, null)).toBe(true);
  expect(deferLegacyInput(true, { ...shared, attempts: 2, result: { state: 'gathering' } }, null)).toBe(false);
  expect(deferLegacyInput(true, { ...shared, attempts: 3, result: { state: 'connecting' } }, null)).toBe(false);
  expect(deferLegacyInput(true, { ...shared, attempts: 4, active: true, result: { state: 'connected' } }, null)).toBe(true);
  // A still-active video with missing control is a different failure boundary.
  expect(deferLegacyInput(true, { ...shared, active: true, result: { state: 'failed' } }, null)).toBe(true);
});
