// Playwright CLI: run-code --filename web-browser-run.js
// Use a fresh named headless session with a loopback Next.js development server.
async page => {
  const origin = 'http://127.0.0.1:49498';
  const context = page.context();
  const id = '00000000-0000-4000-8000-000000000001';
  const org = '00000000-0000-4000-8000-000000000002';
  const actor = { id, org_id: org, email: 'audit@example.invalid', role: 'super_admin', mfa_enabled: false };
  const grants = ['monitoring:read', 'device:read', 'device:write', 'stream:read', 'script:read', 'script:write', 'pipeline:read', 'pipeline:write', 'account:read', 'event:read', 'session:read', 'vpn:read', 'user:read', 'audit:read'];
  const listing = { items: [], total: 0, page: 1, per_page: 50, page_size: 50, pages: 0, total_pages: 0, servers: [], devices: [], profiles: [], rows: [], results: [] };
  const device = { id, org_id: org, name: 'Audit fixture Android', status: 'offline', tags: [], is_active: true, capabilities: [], groups: [] };
  const fallbackPaths = new Set();
  const cases = [
    ['/', '/dashboard'], ['/login'], ['/dashboard'], ['/monitoring'], ['/devices'], [`/devices/${id}`],
    ['/stream'], [`/stream/${id}`], ['/discovery'], ['/fleet', '/groups'], ['/groups'], ['/locations'],
    ['/tasks'], [`/tasks/${id}`], ['/orchestration'], ['/pipeline-settings'], ['/accounts'], ['/scripts'],
    ['/scripts/builder'], ['/events'], ['/event-triggers'], ['/sessions'], ['/vpn'], ['/webhooks'],
    ['/users'], ['/audit'], ['/logs'], ['/updates'], ['/settings'],
  ];

  await context.addInitScript(() => {
    if (location.pathname === '/login') localStorage.setItem('sphere_signed_out', '1');
    else localStorage.removeItem('sphere_signed_out');
  });
  await context.routeWebSocket('**/*', async socket => {
    const url = new URL(socket.url());
    if (url.hostname === '127.0.0.1' && url.port === '49498' && url.pathname === '/_next/webpack-hmr') socket.connectToServer();
    else await socket.close({ code: 1000, reason: 'audit fixture' });
  });
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) return route.abort();
    if (!url.pathname.startsWith('/api/') && !url.pathname.startsWith('/observability/')) return route.continue();
    const endpoint = url.pathname.replace(/^\/api\/v1/, '').replace(/\/$/, '');
    const respond = (json, status = 200) => route.fulfill({ status, json });
    if (endpoint === '/auth/refresh') return respond({ access_token: 'synthetic-access', user: actor });
    if (request.method() !== 'GET') return respond({ detail: 'Writes disabled in audit fixture' }, 405);
    if (endpoint === '/auth/capabilities') return respond({ schema_version: 1, user_id: actor.id, org_id: org, role: actor.role, permissions: grants });
    if (endpoint === '/auth/me') return respond(actor);
    if (endpoint === '/auth/api-keys') return respond([]);
    if (endpoint === `/devices/${id}`) return respond(device);
    if (endpoint === '/locations' || endpoint === '/groups') return respond([]);
    if (endpoint === '/pipeline-settings/servers') return respond([]);
    if (endpoint === '/monitoring/nodes') return respond([]);
    if (endpoint === '/device-events/stats') return respond({ total: 0, unprocessed: 0, by_severity: {}, by_type: {} });
    if (endpoint === '/health') return respond({ status: 'ok' });
    if (endpoint === `/tasks/${id}`) return respond({ detail: 'Audit fixture task absent' }, 404);
    if (endpoint.startsWith('/api/observability') || endpoint.startsWith('/observability/')) return respond({ detail: 'Observability offline in audit fixture' }, 503);
    if (['/accounts/stats', '/game-accounts/stats', '/account-sessions/stats'].includes(endpoint)) return respond(null);
    fallbackPaths.add(endpoint);
    return respond(listing);
  });

  async function observe(tab, requested, expected = requested) {
    const errors = [];
    const onError = error => errors.push(error.message.slice(0, 240));
    tab.on('pageerror', onError);
    try {
      const response = await tab.goto(origin + requested, { waitUntil: 'domcontentloaded', timeout: 75_000 });
      const content = requested === '/login' ? tab.locator('body') : tab.locator('#main-content');
      const marker = requested === '/scripts/builder' ? content.locator('[data-route-scroll="studio-actions"]')
        : requested.startsWith('/tasks/') ? content.getByRole('alert').first()
        : requested === '/login' ? content.locator('#email')
        : requested === '/logs' ? content.getByText('Выберите устройство, чтобы просмотреть логи.', { exact: true })
        : content.locator('h1').first();
      await marker.waitFor({ state: 'visible', timeout: 15_000 });
      if (!['/login', '/logs', '/scripts/builder'].includes(requested) && !requested.startsWith('/tasks/')) {
        await tab.waitForFunction(() => {
          const text = document.querySelector('#main-content h1')?.textContent ?? '';
          return Boolean(text.trim()) && !/Проверяем доступ|Не удалось проверить права|недоступен для вашей роли/.test(text);
        }, undefined, { timeout: 12_000 });
      }
      const status = response?.status() ?? null;
      const path = new URL(tab.url()).pathname;
      return { requested, expected, path, status, result: path === expected && status === 200 && !errors.length ? 'rendered' : 'check',
        marker: (requested === '/login' ? await marker.getAttribute('id') : await marker.innerText()).trim().replace(/\s+/g, ' ').slice(0, 110), errors };
    } catch (error) {
      const headings = await tab.locator('h1').allTextContents().catch(() => []);
      return { requested, expected, path: new URL(tab.url()).pathname, result: 'check', headings,
        errors, detail: String(error.message).split('\n')[0] };
    } finally {
      tab.off('pageerror', onError);
    }
  }

  // Login changes this fixture's local session state. Observe it before other tabs.
  const login = await observe(page, '/login');
  const spare = await context.newPage();
  const rows = [login];
  const authorized = cases.filter(([path]) => path !== '/login');
  await Promise.all([page, spare].map(async (tab, lane) => {
    for (let index = lane; index < authorized.length; index += 2) {
      rows.push(await observe(tab, ...authorized[index]));
    }
  }));
  await spare.close();
  return { chromium: context.browser()?.version(), rows: rows.sort((left, right) => cases.findIndex(([path]) => path === left.requested) - cases.findIndex(([path]) => path === right.requested)), fallbackPaths: [...fallbackPaths].sort() };
}
