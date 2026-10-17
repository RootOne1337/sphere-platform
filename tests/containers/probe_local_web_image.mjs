/** Finite packaged-image HTTP admission. No browser/API/device acceptance is implied. */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { writeFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { pageRoutes, verifyPages } from './frontend_standalone_probe.mjs';

function command(args) {
  const result = spawnSync('docker', args, { encoding: 'utf8', timeout: 30000, maxBuffer: 1024 * 1024 });
  assert.ok(!result.error && result.status === 0, 'Image probe command failed');
  return result.stdout.trim();
}

async function run() {
  const [image, name, output] = process.argv.slice(2);
  assert.match(image ?? '', /^sha256:[a-f0-9]{64}$/);
  assert.match(name ?? '', /^sphere-local-web-probe-[a-f0-9]{16}$/);
  const raw = command(['run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
    '--security-opt', 'no-new-privileges', image, 'node', '-e',
    'process.stdout.write(require("fs").readFileSync(".next/server/app-paths-manifest.json","utf8"))']);
  assert.ok(Buffer.byteLength(raw) <= 256 * 1024);
  const routes = pageRoutes(JSON.parse(raw));
  let owned = false, result;
  try {
    const id = command(['run', '--detach', '--name', name, '--read-only', '--cap-drop', 'ALL',
      '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m',
      '--publish', '127.0.0.1::3000', image]);
    assert.match(id, /^[a-f0-9]{64}$/); owned = true;
    const runtime = JSON.parse(command(['inspect', name]))[0];
    assert.equal(runtime.Image, image);
    const bindings = runtime.NetworkSettings.Ports['3000/tcp'];
    assert.equal(bindings.length, 1); assert.equal(bindings[0].HostIp, '127.0.0.1');
    assert.match(bindings[0].HostPort, /^[0-9]+$/);
    const origin = `http://127.0.0.1:${bindings[0].HostPort}`;
    let ready = false;
    for (let n = 0; n < 80; n++) {
      try {
        const response = await fetch(`${origin}/login`, { signal: AbortSignal.timeout(1000) });
        await response.body.cancel();
        if (response.status === 200) { ready = true; break; }
      } catch { /* Readiness only. Page/asset admission below is not retried. */ }
      await delay(250);
    }
    assert.ok(ready, 'Packaged UI did not become ready');
    result = { imageId: image, loopbackOnly: true, readOnlyContainer: true, ...await verifyPages(origin, routes) };
  } finally { if (owned) command(['rm', '--force', name]); }
  result.ownedContainerRemoved = true;
  await writeFile(output, `${JSON.stringify(result, null, 2)}\n`, { flag: 'wx' });
  console.log(JSON.stringify({ pages: result.pages.length, clientAssets: result.clientAssetsVerified, imageId: image }));
}

run().catch(error => { console.error(error.message); process.exitCode = 1; });
