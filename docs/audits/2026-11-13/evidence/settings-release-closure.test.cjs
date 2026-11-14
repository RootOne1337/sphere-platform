const React = require('react');
const { act, fireEvent, render, screen, waitFor } = require('@testing-library/react');
const { createWrapper } = require('@/__tests__/helpers');

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), delete: jest.fn() } }));

const { api } = require('@/lib/api');
const { useAuthStore } = require('@/lib/store');
const { useUIStore } = require('@/src/shared/store/useUIStore');
const { useThemeStore } = require('@/src/shared/store/themeStore');
const { AppearanceDrawer } = require('@/src/features/preferences/AppearanceDrawer');
const { AgentDownloadPanel } = require('@/src/features/updates/AgentDownloadPanel');
const UpdatesPage = require('@/app/(dashboard)/updates/page').default;

beforeEach(() => { api.get.mockReset(); api.delete.mockReset(); });
afterEach(() => { jest.restoreAllMocks(); useAuthStore.setState({ user: null, sessionVersion: 0 }); });

it('sends two release deletions while the first request has no receipt', async () => {
  useAuthStore.setState({ user: { id: 'fixture-user', org_id: 'fixture-org', role: 'super_admin' }, sessionVersion: 1 });
  const release = { id: 'fixture-release', platform: 'android', flavor: 'dev', version_code: 10255, version_name: '1.2.55-dev',
    download_url: 'https://example.test/fixture.apk', sha256: 'a'.repeat(64), mandatory: false, created_at: '2026-11-13T10:00:00Z' };
  let catalog = [release];
  api.get.mockImplementation(async () => ({ data: { releases: catalog, total: catalog.length } }));
  jest.spyOn(window, 'confirm').mockReturnValue(true);
  const alert = jest.spyOn(window, 'alert').mockImplementation(() => {});
  let first;
  api.delete.mockImplementationOnce(() => new Promise((_, reject) => { first = reject; }))
    .mockRejectedValueOnce(Object.assign(new Error('Request failed with status code 404'), { response: { status: 404 } }));
  render(React.createElement(UpdatesPage), { wrapper: createWrapper() });
  const button = await screen.findByRole('button', { name: 'Delete' });
  fireEvent.click(button);
  catalog = [];
  expect(button).toBeEnabled();
  fireEvent.click(button);
  expect(api.delete.mock.calls).toEqual([['/updates/fixture-release'], ['/updates/fixture-release']]);
  await act(async () => first(new Error('timeout of 5000ms exceeded')));
  expect(alert).toHaveBeenCalledWith('Request failed with status code 404');
  expect(alert).toHaveBeenCalledWith('timeout of 5000ms exceeded');
  expect(screen.getByText('v1.2.55-dev')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Обновить релизы' }));
  expect(await screen.findByText('Опубликованных релизов пока нет.')).toBeInTheDocument();
});

it('overwrites newer appearance preferences after a cross-tab storage update', () => {
  useThemeStore.setState({ theme: 'neo-dark', density: 'cozy' });
  useUIStore.setState({ accentColor: 'emerald', fontSize: 'base', surfaceStyle: 'glass' });
  const view = render(React.createElement(AppearanceDrawer, { open: true, onClose: jest.fn() }));
  const key = 'sphere-ui-preferences';
  const oldValue = localStorage.getItem(key);
  const later = JSON.parse(oldValue);
  later.state.fontSize = 'lg';
  later.state.surfaceStyle = 'solid';
  const newValue = JSON.stringify(later);
  localStorage.setItem(key, newValue);
  act(() => window.dispatchEvent(new StorageEvent('storage', { key, oldValue, newValue })));
  expect(useUIStore.getState().fontSize).toBe('base');
  expect(useUIStore.getState().surfaceStyle).toBe('glass');
  fireEvent.click(screen.getByRole('button', { name: 'Акцент темы' }));
  expect(JSON.parse(localStorage.getItem(key)).state).toMatchObject({ accentColor: 'theme', fontSize: 'base', surfaceStyle: 'glass' });
  view.unmount();
  localStorage.removeItem(key);
});

it('offers an APK to the browser even when its bytes disagree with the response checksum', async () => {
  const { createHash } = require('node:crypto');
  const bytes = Buffer.from('synthetic-corrupted-fixture');
  const expectedDigest = createHash('sha256').update('synthetic-original-fixture').digest('hex');
  expect(createHash('sha256').update(bytes).digest('hex')).not.toBe(expectedDigest);
  const descriptors = Object.getOwnPropertyDescriptors(URL);
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: jest.fn(() => 'blob:fixture') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: jest.fn() });
  const clicked = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  try {
    api.get.mockResolvedValue({ data: new Blob([bytes]), headers: {
      'content-type': 'application/vnd.android.package-archive', 'content-disposition': 'attachment; filename="fixture.apk"',
      'x-sphere-apk-sha256': expectedDigest, 'x-sphere-version-code': '10255',
    } });
    const view = render(React.createElement(AgentDownloadPanel, { releases: [], available: true }));
    fireEvent.click(screen.getByRole('button', { name: 'Скачать последний APK' }));
    await screen.findByText('APK передан браузеру для сохранения.');
    await waitFor(() => expect(clicked).toHaveBeenCalledTimes(1));
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    view.unmount();
  } finally {
    for (const key of ['createObjectURL', 'revokeObjectURL']) {
      if (descriptors[key]) Object.defineProperty(URL, key, descriptors[key]);
      else delete URL[key];
    }
  }
});
