/** Exercise the packaged Next server, not `next dev` or the source checkout. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { access, readFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const MAX_HTML = 2 * 1024 * 1024;
const MAX_ASSET = 16 * 1024 * 1024;

async function boundedBody(response, limit) {
  const reader = response.body.getReader();
  const parts = [];
  let bytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      assert.ok(bytes <= limit, 'HTTP response exceeds probe budget');
      parts.push(Buffer.from(value));
    }
    return Buffer.concat(parts).toString('utf8');
  } finally { await reader.cancel(); }
}

export function pageRoutes(manifest) {
  assert.ok(manifest && typeof manifest === 'object' && !Array.isArray(manifest), 'Invalid app manifest');
  assert.ok(Object.keys(manifest).length <= 512, 'App manifest exceeds budget');
  const routes = new Set();
  for (const key of Object.keys(manifest)) {
    if (!key.endsWith('/page') || key.includes('[') || key.includes('/_not-found/')) continue;
    const route = key.replace(/\/\([^/]+\)/g, '').replace(/\/page$/, '') || '/';
    assert.match(route, /^\/[a-zA-Z0-9/_-]*$/, 'Unexpected page route');
    routes.add(route);
  }
  for (const required of ['/', '/login', '/scripts', '/scripts/builder', '/devices', '/monitoring']) {
    assert.ok(routes.has(required), `Required route absent: ${required}`);
  }
  return [...routes].sort();
}

/** Next may emit its redirect after a streamed/prerendered HTTP 200 shell.
 * Inspect the framework redirect payload; a generic 200 or arbitrary token is
 * not sufficient. JSON is parsed as data, never evaluated as JavaScript. */
function rootRedirect(response, html, origin) {
  if ([307, 308].includes(response.status)) {
    const location = response.headers.get('location');
    assert.ok(location, 'Root redirect has no Location');
    const target = new URL(location, origin);
    assert.equal(target.origin, origin, 'External root redirect');
    assert.equal(target.pathname + target.search + target.hash, '/dashboard');
    return 'http';
  }
  assert.equal(response.status, 200, `Root failed: ${response.status}`);
  assert.match(response.headers.get('content-type') ?? '', /text\/html/, 'Root is not HTML');
  for (const match of html.matchAll(/<meta\b[^>]*>/g)) {
    const attributes = Object.fromEntries([...match[0].matchAll(/([\w-]+)=["']([^"']*)["']/g)].map(row => [row[1].toLowerCase(), row[2]]));
    if (attributes.id === '__next-page-redirect' && attributes['http-equiv'] === 'refresh'
      && /^[01];url=\/dashboard$/.test(attributes.content ?? '')) return 'next-meta';
  }
  for (const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
    const call = match[1].match(/^self\.__next_f\.push\(([\s\S]*)\);?$/);
    if (!call) continue;
    let payload;
    try { payload = JSON.parse(call[1]); } catch { continue; }
    if (!Array.isArray(payload) || payload[0] !== 1 || typeof payload[1] !== 'string') continue;
    for (const line of payload[1].split('\n')) {
      const error = line.match(/^[\da-f]+:E(\{.*\})$/);
      if (!error) continue;
      let data;
      try { data = JSON.parse(error[1]); } catch { continue; }
      if (data && /^NEXT_REDIRECT;(?:replace|push);\/dashboard;(?:307|308);$/.test(data.digest)) return 'next-flight';
    }
  }
  throw new Error('Root 200 has no verified Next redirect to /dashboard');
}

export async function verifyPages(origin, routes) {
  const assets = new Set();
  const pages = [];
  for (const route of routes) {
    const response = await fetch(new URL(route, origin), { redirect: 'manual', signal: AbortSignal.timeout(10000) });
    const html = await boundedBody(response, MAX_HTML);
    assert.ok(!html.includes('NEXT_HTTP_ERROR_FALLBACK;500'), `SSR error: ${route}`);
    let redirect;
    if (route === '/') {
      redirect = rootRedirect(response, html, origin);
    } else {
      assert.equal(response.status, 200, `Page failed: ${route} (${response.status})`);
      assert.match(response.headers.get('content-type') ?? '', /text\/html/, `Not HTML: ${route}`);
      let scripts = 0;
      for (const match of html.matchAll(/\b(?:src|href)=["']([^"']+)["']/g)) {
        const value = match[1].replaceAll('&amp;', '&');
        if (!value.startsWith('/_next/static/')) continue;
        const url = new URL(value, origin);
        assert.equal(url.origin, origin, 'External asset URL');
        assets.add(url.pathname + url.search);
        if (/\.js(?:\?|$)/.test(value)) scripts++;
      }
      assert.ok(scripts > 0, `No client JS advertised: ${route}`);
    }
    pages.push({ route, status: response.status, ...(redirect ? { redirect } : {}) });
  }
  assert.ok(assets.size <= 512, 'Client asset count exceeds probe budget');
  for (const path of assets) {
    const response = await fetch(new URL(path, origin), { redirect: 'manual', signal: AbortSignal.timeout(10000) });
    assert.equal(response.status, 200, `Client asset missing: ${path} (${response.status})`);
    const body = await boundedBody(response, MAX_ASSET);
    assert.ok(body.length > 0, `Empty client asset: ${path}`);
    const type = response.headers.get('content-type') ?? '';
    assert.ok(!type.includes('text/html'), `HTML served instead of asset: ${path}`);
    if (/\.js(?:\?|$)/.test(path)) assert.match(type, /(?:javascript|ecmascript)/, `Not JS: ${path}`);
    if (/\.css(?:\?|$)/.test(path)) assert.match(type, /text\/css/, `Not CSS: ${path}`);
  }
  return { pages, clientAssetsVerified: assets.size, browserHydrationVerified: false, backendExecutionVerified: false };
}

async function run() {
  const artifact = resolve(process.argv[2] ?? 'frontend/.next/standalone');
  const entry = resolve(artifact, 'server.js');
  await access(entry);
  const raw = await readFile(resolve(artifact, '.next/server/app-paths-manifest.json'));
  assert.ok(raw.byteLength <= 256 * 1024, 'Manifest exceeds byte budget');
  const routes = pageRoutes(JSON.parse(raw.toString('utf8')));
  const reservation = createServer();
  await new Promise((done, reject) => { reservation.once('error', reject); reservation.listen(0, '127.0.0.1', done); });
  const port = reservation.address().port;
  await new Promise(done => reservation.close(done));
  const origin = `http://127.0.0.1:${port}`;
  const child = spawn(process.execPath, [entry], {
    cwd: artifact, stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, NODE_ENV: 'production', HOSTNAME: '127.0.0.1', PORT: String(port), NEXT_TELEMETRY_DISABLED: '1' },
  });
  let output = '';
  const collect = data => { output = (output + data.toString()).slice(-16384); };
  child.stdout.on('data', collect); child.stderr.on('data', collect);
  let launchError;
  child.on('error', error => { launchError = error; });
  try {
    let ready = false;
    for (let attempt = 0; attempt < 120; attempt++) {
      if (launchError) throw launchError;
      assert.equal(child.exitCode, null, 'Packaged server exited before ready');
      try {
        const response = await fetch(new URL('/login', origin), { signal: AbortSignal.timeout(1000) });
        await boundedBody(response, MAX_HTML);
        if (response.status === 200) { ready = true; break; }
      } catch { /* Only startup connection failures are retried; page checks are not. */ }
      await delay(250);
    }
    assert.ok(ready, 'Packaged server did not become ready');
    const receipt = await verifyPages(origin, routes);
    console.log(JSON.stringify({ artifact: '.next/standalone', loopbackOnly: true, ...receipt }));
  } catch (error) {
    // CI output is bounded; request bodies, API credentials and pages are never printed.
    console.error(output);
    throw error;
  } finally {
    child.kill('SIGTERM');
    await Promise.race([new Promise(done => child.once('exit', done)), delay(5000)]);
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  run().catch(error => { console.error(error.message); process.exitCode = 1; });
}
