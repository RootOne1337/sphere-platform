import assert from 'node:assert/strict';
import test from 'node:test';
import { packageCommandFailure } from './package_command_failure.mjs';
import { buildReviewedWebImage } from './reviewed_web_image_build.mjs';

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

test('archive admission reports a bounded rule code without reflecting arbitrary output', () => {
  const verdict = { archiveAdmitted: false, runtimeInstalled: false, reasonCode: 'image_config_digest_mismatch' };
  assert.equal(packageCommandFailure({ stdout: JSON.stringify(verdict) }), 'archive_admission:image_config_digest_mismatch');
  for (const changed of [{ ...verdict, reasonCode: 'raw private text\n' }, { ...verdict, runtimeInstalled: true }]) {
    assert.equal(packageCommandFailure({ stdout: JSON.stringify(changed) }), 'unclassified');
  }
});

test('a registry quota refusal uses the identical pinned official image once', () => {
  const calls = [];
  const result = buildReviewedWebImage(['--label', 'source=fixed', '/tested-output'], (program, args) => {
    calls.push({ program, args });
    return calls.length === 1 ? { status: 1, stderr: '429 Too Many Requests private-token' } : { status: 0 };
  });
  assert.deepEqual(result, { registry: 'hub', mirrorFallback: true });
  assert.equal(calls.length, 2);
  const digest = 'sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20';
  for (const [index, call] of calls.entries()) {
    assert.equal(call.program, 'docker');
    assert.deepEqual(call.args.slice(0, 3), ['build', '--label', 'source=fixed']);
    assert.equal(call.args.at(-1), '/tested-output');
    assert.ok(call.args.includes(`NODE_BASE_IMAGE=${index === 0 ? 'public.ecr.aws/docker/library/node' : 'docker.io/library/node'}@${digest}`));
  }
});

test('ordinary build failures and timeouts never trigger a registry fallback', () => {
  for (const result of [{ status: 1, stderr: 'COPY failed private-path' }, { error: { code: 'ETIMEDOUT' }, stderr: '429 Too Many Requests' }]) {
    let calls = 0;
    assert.throws(() => buildReviewedWebImage(['/tested-output'], () => { calls++; return result; }), error => {
      assert.doesNotMatch(error.message, /private-path|Too Many Requests/);
      return true;
    });
    assert.equal(calls, 1);
  }
});

test('two unavailable official registries remain a bounded failed build', () => {
  let calls = 0;
  assert.throws(() => buildReviewedWebImage(['/tested-output'], () => { calls++; return { status: 1, stderr: 'toomanyrequests private-token' }; }), /registry_rate_limit/);
  assert.equal(calls, 2);
});
