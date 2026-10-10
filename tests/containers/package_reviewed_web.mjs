/** Hosted CI only: package tested standalone files and admit the actual image. */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { pageRoutes, verifyPages } from './frontend_standalone_probe.mjs';
import { packageCommandFailure } from './package_command_failure.mjs';

function command(program, args, timeout = 120000) {
  const result = spawnSync(program, args, { encoding: 'utf8', timeout, maxBuffer: 256 * 1024 });
  // No arbitrary command stdout, environment or Docker config is printed.
  assert.ok(!result.error && result.status === 0,
    `${program} failed (${result.status ?? 'no exit code'}; ${packageCommandFailure(result)})`);
  return result.stdout.trim();
}

async function run() {
  assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Hosted CI packaging only');
  assert.equal(process.platform, 'linux');
  const source = command('git', ['rev-parse', 'HEAD']);
  assert.match(source, /^[a-f0-9]{40}$/);
  assert.equal(source, process.env.NEXT_PUBLIC_BUILD_SHA, 'Source/build revision mismatch');
  const runId = process.env.SPHERE_CI_RUN_ID;
  const runAttempt = process.env.SPHERE_CI_RUN_ATTEMPT;
  assert.match(runId ?? '', /^[1-9][0-9]*$/);
  assert.match(runAttempt ?? '', /^[1-9][0-9]*$/);
  const artifact = resolve('.next/standalone');
  const raw = await readFile(resolve(artifact, '.next/server/app-paths-manifest.json'));
  assert.ok(raw.byteLength <= 256 * 1024);
  const routes = pageRoutes(JSON.parse(raw.toString('utf8')));
  const image = `sphere-review-frontend:${source}`;
  const name = `sphere-reviewed-web-ci-${runId}-${runAttempt}`;
  command('docker', ['build', '--platform', 'linux/amd64', '--label', `io.sphere.ci.run=${runId}`, '--label', `io.sphere.ci.attempt=${runAttempt}`,
    '--build-arg', `BUILD_SHA=${source}`, '-f', resolve('../tests/containers/frontend_review.Dockerfile'), '-t', image, artifact], 240000);
  const imageId = command('docker', ['image', 'inspect', '--format', '{{.Id}}', image]);
  assert.match(imageId, /^sha256:[a-f0-9]{64}$/);
  let owned = false;
  let probe;
  try {
    const id = command('docker', ['run', '--detach', '--name', name, '--read-only', '--cap-drop', 'ALL',
      '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m',
      '--publish', '127.0.0.1::3000', imageId]);
    assert.match(id, /^[a-f0-9]{64}$/);
    owned = true;
    const ports = JSON.parse(command('docker', ['inspect', '--format', '{{json .NetworkSettings.Ports}}', name]));
    const binding = ports['3000/tcp'];
    assert.equal(binding?.length, 1);
    assert.equal(binding[0].HostIp, '127.0.0.1');
    assert.match(binding[0].HostPort, /^[0-9]+$/);
    const origin = `http://127.0.0.1:${binding[0].HostPort}`;
    let ready = false;
    for (let attempt = 0; attempt < 80; attempt++) {
      try {
        const response = await fetch(`${origin}/login`, { signal: AbortSignal.timeout(1000) });
        await response.body.cancel();
        if (response.status === 200) { ready = true; break; }
      } catch { /* Startup only. Final page/asset errors are never retried. */ }
      await delay(250);
    }
    assert.ok(ready, 'Runtime image did not become ready');
    probe = await verifyPages(origin, routes);
  } finally {
    if (owned) command('docker', ['rm', '--force', name], 15000);
  }
  const output = resolve('reviewed-web');
  await mkdir(output, { recursive: false });
  const archive = resolve(output, 'image.tar');
  command('docker', ['image', 'save', '--output', archive, image], 120000);
  assert.ok((await stat(archive)).size <= 1024 * 1024 * 1024, 'Uncompressed image budget exceeded');
  command('gzip', ['-n', '-1', archive], 120000);
  const compressed = `${archive}.gz`;
  const bytes = (await stat(compressed)).size;
  assert.ok(bytes > 0 && bytes <= 300 * 1024 * 1024, 'Compressed image budget exceeded');
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(compressed)) hash.update(chunk);
  const receipt = {
    schemaVersion: 1, sourceRevision: source, runId: Number(runId), runAttempt: Number(runAttempt),
    repository: 'RootOne1337/sphere-platform', observedAtUtc: new Date().toISOString(),
    image: { tag: image, id: imageId, os: 'linux', architecture: 'amd64' },
    archive: { file: 'image.tar.gz', bytes, sha256: hash.digest('hex'), maxExpandedBytes: 1024 * 1024 * 1024 },
    probe: { loopbackOnly: true, readOnlyContainer: true, ...probe },
    runtimeInstalled: false,
  };
  await writeFile(resolve(output, 'receipt.json'), `${JSON.stringify(receipt, null, 2)}\n`, { flag: 'wx' });
  command('python', [resolve('../scripts/pilot/reviewed_web_artifact.py'), '--directory', output, '--source', source]);
  console.log(JSON.stringify({ source, imageId, compressedBytes: bytes, pages: probe.pages.length,
    assets: probe.clientAssetsVerified, runId: receipt.runId, runtimeInstalled: false }));
}

run().catch(error => { console.error(error.message); process.exitCode = 1; });
