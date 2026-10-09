import assert from 'node:assert/strict';
import test from 'node:test';
import { packageCommandFailure } from './package_command_failure.mjs';

test('registry failure is distinguishable without exposing raw stderr', () => {
  for (const message of ['toomanyrequests: secret-token', '429 Too Many Requests: secret-token',
    'You have reached your unauthenticated pull rate limit: secret-token']) {
    assert.equal(packageCommandFailure({ status: 1, stderr: message }), 'registry_rate_limit');
  }
});
test('timeout, output budget and unavailable program are separate outcomes', () => {
  for (const [code, expected] of [['ETIMEDOUT', 'timeout'], ['ENOBUFS', 'output_budget'],
    ['ENOENT', 'program_unavailable']]) {
    assert.equal(packageCommandFailure({ error: { code, message: 'private' }, stderr: 'toomanyrequests' }), expected);
  }
});
test('unknown process errors retain no environment, stdout or private message', () => {
  const result = { error: { code: 'private-code', message: 'private-message' },
    stdout: '429 Too Many Requests private-stdout', stderr: 'private-stderr', status: 1 };
  assert.equal(packageCommandFailure(result), 'unclassified');
});
