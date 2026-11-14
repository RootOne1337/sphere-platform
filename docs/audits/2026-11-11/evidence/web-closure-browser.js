// Run in a fresh Playwright CLI session after the two loopback servers are up.
async page => {
  const origin = 'http://127.0.0.1:49498';
  const task = '00000000-0000-0000-0000-000000000003';
  const context = page.context();
  await context.route('**/*', async route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  await context.routeWebSocket('**/*', async socket => {
    const target = new URL(socket.url());
    if (target.hostname === '127.0.0.1' && target.port === '49498' && target.pathname === '/_next/webpack-hmr') socket.connectToServer();
    else await socket.close({ code: 1000, reason: 'audit fixture' });
  });

  await page.goto(`${origin}/stream`, { waitUntil: 'domcontentloaded' });
  const next = page.getByRole('button', { name: 'Следующая страница' });
  await next.waitFor({ state: 'visible' });
  const pageButtonSnapshot = await next.ariaSnapshot();
  const aborted = page.waitForEvent('requestfailed', { predicate: request => {
    const url = new URL(request.url());
    return url.pathname === '/api/v1/devices' && url.searchParams.get('page') === '2';
  }, timeout: 12_000 });
  await next.click();
  const pageTwo = await aborted;
  const pager = page.getByRole('navigation', { name: 'Страницы списка устройств' });
  await pager.getByText('1 / 2', { exact: true }).waitFor();
  const stream = {
    before: pageButtonSnapshot, request: new URL(pageTwo.url()).pathname + new URL(pageTwo.url()).search,
    failure: pageTwo.failure()?.errorText, pager: await pager.getByText('1 / 2', { exact: true }).innerText(),
    fifthDeviceVisible: await page.getByText('Audit Android 5', { exact: true }).isVisible(),
  };

  const capResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/auth/capabilities');
  await page.goto(`${origin}/tasks/${task}`, { waitUntil: 'domcontentloaded' });
  const permissions = await (await capResponse).json();
  const stop = page.getByRole('button', { name: 'Остановить задание' });
  await stop.waitFor({ state: 'visible' });
  const enabled = await stop.isEnabled();
  const stopSnapshot = await stop.ariaSnapshot();
  const stopResponse = page.waitForResponse(response => new URL(response.url()).pathname === `/api/v1/tasks/${task}/stop`);
  await stop.click();
  const response = await stopResponse;
  const detail = await response.json();
  const message = page.getByRole('alert').filter({ hasText: 'Permission denied: script:execute' });
  await message.waitFor({ state: 'visible' });
  if (permissions.role !== 'viewer' || !permissions.permissions.includes('script:read') || permissions.permissions.includes('script:execute') || !enabled || response.status() !== 403 || stream.fifthDeviceVisible) throw new Error('Unexpected closure evidence');
  return {
    chromium: context.browser()?.version(), stream,
    task: { role: permissions.role, readGranted: true, executeGranted: false, before: stopSnapshot,
      buttonEnabled: enabled, responseStatus: response.status(), responseDetail: detail.detail, displayed: await message.innerText() },
  };
}
