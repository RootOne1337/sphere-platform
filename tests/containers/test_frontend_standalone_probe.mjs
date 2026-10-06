import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { test } from 'node:test';
import { pageRoutes, verifyPages } from './frontend_standalone_probe.mjs';

const manifest = Object.fromEntries(['/', '/login', '/scripts', '/scripts/builder', '/devices', '/monitoring']
  .map(route => [`${route === '/' ? '' : route}/page`, 'unused.js']));

test('manifest checks every concrete page, deduplicates groups and requires core product routes', () => {
  const routes = pageRoutes({ ...manifest, '/(dashboard)/scripts/page': 'duplicate.js',
    '/(dashboard)/groups/page': 'groups.js', '/scripts/[id]/page': 'dynamic.js',
    '/api/observability/route': 'api.js', '/_not-found/page': 'internal.js' });
  assert.equal(routes.filter(route => route === '/scripts').length, 1);
  assert.ok(routes.includes('/groups'));
  assert.ok(!routes.some(route => route.includes('[') || route.includes('api/') || route.includes('_not-found')));
  assert.throws(() => pageRoutes({}), /Required route absent/);
  assert.throws(() => pageRoutes({ ...manifest, '/..\/outside/page': 'bad.js' }), /Unexpected page route/);
});

async function withPages(t, alteration = {}) {
  const seen = [];
  const server = createServer((request, response) => {
    seen.push(request.url);
    if (request.url === '/') {
      response.writeHead(alteration.rootStatus ?? 307, { location: alteration.location ?? '/dashboard', 'content-type': 'text/html' });
      response.end(alteration.rootHtml ?? '');
    } else if (request.url.startsWith('/_next/static/')) {
      response.writeHead(alteration.assetStatus ?? 200, { 'content-type': alteration.assetType ?? 'text/javascript' });
      response.end(alteration.assetBody ?? 'window.packagedChunk = true;');
    } else {
      response.writeHead(alteration.pageStatus ?? 200, { 'content-type': alteration.pageType ?? 'text/html' });
      response.end(alteration.html ?? '<html><script src="/_next/static/chunks/app.js"></script></html>');
    }
  });
  await new Promise(done => server.listen(0, '127.0.0.1', done));
  t.after(() => { server.closeAllConnections(); return new Promise(done => server.close(done)); });
  return { origin: `http://127.0.0.1:${server.address().port}`, seen };
}

test('HTTP receipt requires rendered pages and advertised client assets', async t => {
  const { origin, seen } = await withPages(t);
  const receipt = await verifyPages(origin, pageRoutes(manifest));
  assert.equal(receipt.pages.length, 6);
  assert.equal(receipt.clientAssetsVerified, 1);
  assert.equal(seen.filter(path => path.startsWith('/_next/static/')).length, 1);
  assert.equal(receipt.browserHydrationVerified, false);
  assert.equal(receipt.backendExecutionVerified, false);
});

const flight = digest => `<script>self.__next_f.push(${JSON.stringify([1, `7:E${JSON.stringify({ digest })}\n`])})</script>`;
for (const [kind, rootHtml] of [
  ['next-meta', '<meta id="__next-page-redirect" http-equiv="refresh" content="1;url=/dashboard"/>'],
  ['next-flight', flight('NEXT_REDIRECT;replace;/dashboard;307;')],
]) {
  test(`prerendered root 200 requires verified ${kind} redirect payload`, async t => {
    const { origin } = await withPages(t, { rootStatus: 200, rootHtml });
    const receipt = await verifyPages(origin, pageRoutes(manifest));
    assert.equal(receipt.pages.find(row => row.route === '/').redirect, kind);
  });
}

for (const [name, alteration, expected] of [
  ['SSR failure', { pageStatus: 500 }, /Page failed/],
  ['missing client chunk', { assetStatus: 404 }, /Client asset missing/],
  ['HTML fallback for client chunk', { assetType: 'text/html' }, /HTML served instead/],
  ['empty chunk', { assetBody: '' }, /Empty client asset/],
  ['incorrect root destination', { location: '/missing' }, /\/dashboard/],
  ['error inside streamed HTML with status 200', { html: '<script src="/_next/static/a.js"></script>NEXT_HTTP_ERROR_FALLBACK;500' }, /SSR error/],
  ['no advertised client scripts', { html: '<html>empty shell</html>' }, /No client JS/],
  ['unbounded response', { html: 'x'.repeat(2 * 1024 * 1024 + 1) }, /budget/],
  ['external HTTP redirect', { location: 'https://example.com/dashboard' }, /External root redirect/],
  ['empty root 200', { rootStatus: 200 }, /no verified Next redirect/],
  ['incorrect RSC destination', { rootStatus: 200, rootHtml: flight('NEXT_REDIRECT;replace;/missing;307;') }, /no verified Next redirect/],
  ['plain fake redirect text', { rootStatus: 200, rootHtml: 'NEXT_REDIRECT;replace;/dashboard;307;' }, /no verified Next redirect/],
  ['unsupported redirect status', { rootStatus: 200, rootHtml: flight('NEXT_REDIRECT;replace;/dashboard;302;') }, /no verified Next redirect/],
  ['invalid meta destination', { rootStatus: 200, rootHtml: '<meta id="__next-page-redirect" http-equiv="refresh" content="1;url=https://example.com/dashboard"/>' }, /no verified Next redirect/],
]) {
  test(`packaged probe rejects ${name}`, async t => {
    const { origin } = await withPages(t, alteration);
    await assert.rejects(verifyPages(origin, pageRoutes(manifest)), expected);
  });
}
