// Playwright CLI run-code --filename <this file>. Serve an isolated Next copy on port 49513.
async page => {
  const origin = 'http://127.0.0.1:49513';
  const id = '00000000-0000-4000-8000-000000000001';
  const org = '00000000-0000-4000-8000-000000000002';
  const actor = { id, org_id: org, email: 'audit@example.invalid', role: 'super_admin', mfa_enabled: false };
  const permissions = ['monitoring:read', 'device:read', 'event:read', 'pipeline:read', 'audit:read', 'vpn:read', 'user:read'];
  const time = '2026-11-13T09:00:00Z';
  const logs = ['2026-11-13T09:00:00Z E/SphereAgent: fixture error', '11-13 09:00:00.000 321 321 E SphereAgent: threadtime error', '=== RECENT SPHERE CRASH ===', 'No persisted uncaught crash record'];
  const calls = [];
  const context = page.context();
  await context.routeWebSocket('**/*', socket => {
    if (socket.url() === 'ws://127.0.0.1:49513/_next/webpack-hmr') socket.connectToServer();
    else return socket.close();
  });
  await context.route('**/*', route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) return route.abort();
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.replace(/^\/api\/v1/, '').replace(/\/$/, '');
    const reply = (json, status = 200) => route.fulfill({ status, json });
    calls.push([request.method(), path, url.search]);
    if (path === '/auth/refresh') return reply({ access_token: 'synthetic-access', user: actor });
    if (request.method() !== 'GET') return reply({ detail: 'Fixture blocks writes' }, 405);
    if (path === '/auth/capabilities') return reply({ schema_version: 1, user_id: id, org_id: org, role: actor.role, permissions });
    if (path === '/auth/me') return reply(actor);
    if (path === `/devices/${id}`) return reply({ id, org_id: org, name: 'Android fixture', status: 'online', tags: [], capabilities: [], groups: [] });
    if (path === `/logs/${id}`) return reply({ device_id: id, lines: logs, total: logs.length });
    if (path === '/device-events/stats') return reply({ total: 41, unprocessed: 18, by_severity: { error: 3 }, by_type: {} });
    if (path === '/device-events') return reply({ items: [], total: url.searchParams.has('search') ? 0 : 41, page: 1, pages: 1 });
    if (path === '/pipelines') return reply({ detail: 'Fixture pipeline options unavailable' }, 503);
    if (path === '/n8n/webhooks') return reply({ total: 1, items: [{ id, name: 'Тестовый endpoint', url: 'https://receiver.example.invalid/events', events: ['task.completed'], is_active: true, created_at: time, last_triggered_at: null, failure_count: 7 }] });
    if (path === '/audit/logs') {
      const pageNumber = Number(url.searchParams.get('page') || 1);
      const items = Array.from({ length: pageNumber === 1 ? 100 : 1 }, (_, index) => ({ id: `${pageNumber}-${index}`, created_at: time, action: 'fixture.check', meta: { status: pageNumber === 1 ? 'success' : 'failed' } }));
      return reply({ items, total: 101, page: pageNumber, pages: 2 });
    }
    return reply({ items: [], total: 0, page: 1, pages: 0, page_size: 50 });
  });

  const output = { chromium: context.browser().version(), checks: {} };
  await page.setViewportSize({ width: 1440, height: 900 });
  const main = page.locator('#main-content');
  async function open(path, title) {
    await page.goto(origin + path, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await main.getByRole('heading', { name: title, exact: true }).waitFor({ timeout: 15000 });
  }
  const headingStyle = heading => heading.evaluate(element => {
    const style = getComputedStyle(element);
    return { fontSize: style.fontSize, fontFamily: style.fontFamily, textTransform: style.textTransform };
  });

  await open('/events', 'События устройств');
  const eventHeading = await headingStyle(main.getByRole('heading', { level: 1 }));
  await main.getByRole('textbox', { name: 'Поиск событий' }).fill('missing-fixture');
  await main.getByText('Журнал событий парка · 0 записей').waitFor();
  await main.getByText('41', { exact: true }).waitFor();
  const refresh = page.waitForResponse(response => response.url().includes('/device-events?') && response.url().includes('missing-fixture'));
  const callOffset = calls.length;
  await main.getByRole('button', { name: 'Обновить' }).click();
  await refresh;
  output.checks.events = { filteredTotal: 0, globalTotal: 41, refreshCalls: calls.slice(callOffset).filter(([, path]) => path.startsWith('/device-events')) };

  await page.setViewportSize({ width: 390, height: 844 });
  await open('/event-triggers', 'Event Triggers');
  const triggerHeading = await headingStyle(main.getByRole('heading', { level: 1 }));
  await main.getByRole('button', { name: /создать|новый/i }).first().click();
  await page.locator('#trigger-pipeline').click();
  await page.getByText('Нет доступных сценариев', { exact: true }).waitFor();
  output.checks.triggers = { eventHeading, triggerHeading, pipelineOptions: '503 → Нет доступных сценариев', viewport: 390 };
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');

  await open('/webhooks', 'Вебхуки');
  const hook = main.getByRole('region', { name: 'Список вебхуков' });
  await hook.getByText('Активен', { exact: true }).waitFor();
  output.checks.webhook = { summary: (await hook.innerText()).replace(/\s+/g, ' '), fixtureFailures: 7, viewport: 390 };

  await page.setViewportSize({ width: 1440, height: 900 });
  await open(`/logs?device_id=${id}`, 'Системные логи');
  const rows = main.getByLabel('Строки системного журнала');
  await rows.getByText('=== RECENT SPHERE CRASH ===', { exact: true }).waitFor();
  const noCrash = await rows.getByText('No persisted uncaught crash record', { exact: true }).isVisible();
  await main.getByRole('combobox', { name: 'Фильтр уровня логов' }).click();
  await page.getByRole('option', { name: 'Ошибки', exact: true }).click();
  await rows.getByText(/fixture error/).waitFor();
  output.checks.logs = { noCrash, fileErrorVisible: true, threadtimeErrorVisible: await rows.getByText(/threadtime error/).isVisible() };

  await open('/audit', 'Журнал аудита');
  const summary = main.getByRole('region', { name: 'Сводка журнала аудита' });
  await summary.getByText('101', { exact: true }).waitFor();
  const auditFirst = (await summary.innerText()).replace(/\s+/g, ' ');
  await main.getByRole('button', { name: 'Следующая страница' }).click();
  await summary.getByText('1', { exact: true }).waitFor();
  output.checks.audit = { first: auditFirst, second: (await summary.innerText()).replace(/\s+/g, ' ') };

  await context.addInitScript(() => {
    localStorage.setItem('sphere-theme-preferences', JSON.stringify({ state: { theme: 'light-corporate', density: 'comfortable' }, version: 0 }));
  });
  await open('/events', 'События устройств');
  await page.locator('html[data-theme="light-corporate"]').waitFor();
  const lightEvents = await headingStyle(main.getByRole('heading', { level: 1 }));
  await page.screenshot({ path: 'output/playwright/operator-nov13-events-light.png' });
  await open('/event-triggers', 'Event Triggers');
  await page.locator('html[data-theme="light-corporate"]').waitFor();
  const lightTriggers = await headingStyle(main.getByRole('heading', { level: 1 }));
  const tableStyle = await main.locator('thead').evaluate(element => {
    const style = getComputedStyle(element);
    return { background: style.backgroundColor, color: style.color };
  });
  await page.screenshot({ path: 'output/playwright/operator-nov13-triggers-light.png' });
  output.checks.lightComparison = { lightEvents, lightTriggers, tableStyle, viewport: 1440 };
  return output;
}
