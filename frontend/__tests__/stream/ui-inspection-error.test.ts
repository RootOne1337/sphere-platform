import { uiInspectionError } from '@/src/features/stream/uiInspectionError';

const fixture = (headers: Record<string, unknown>) => ({ response: { data: { detail: 'compatible error' }, headers: {
  'x-sphere-ui-stage': 'read_xml', 'x-sphere-ui-reason': 'native_exit_nonzero',
  'x-sphere-ui-snapshot': 'a'.repeat(32), ...headers,
} } });

it.each(['0', '256', '-1', '1 secret', '1\nsecret', '9'.repeat(512)])('never renders an untrusted exit header %s', raw => {
  const result = uiInspectionError(fixture({ 'x-sphere-ui-native-exit-code': raw }));
  expect(result.message).toBe('Android завершил команду с ненулевым кодом.');
  expect(result.diagnostic?.nativeExitCode).toBeUndefined();
});
it.each([
  { 'x-sphere-ui-stage': 'constructor' }, { 'x-sphere-ui-reason': '__proto__' },
  { 'x-sphere-ui-snapshot': '<native secret>' }, { 'x-sphere-ui-reason': 'future_unknown_reason' },
])('uses the compatible API message for unknown protocol diagnostics', headers => {
  expect(uiInspectionError(fixture(headers))).toEqual({ message: 'compatible error' });
});
it('does not confuse cleanup status or another native failure with an exit code', () => {
  const result = uiInspectionError(fixture({ 'x-sphere-ui-reason': 'native_input_busy', 'x-sphere-ui-native-exit-code': '1', 'x-sphere-ui-cleanup': 'private stderr' }));
  expect(result.diagnostic?.nativeExitCode).toBeUndefined();
  expect(result.diagnostic?.cleanupUnconfirmed).toBe(false);
  expect(JSON.stringify(result)).not.toMatch(/stderr/);
});
