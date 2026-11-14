import { fireEvent, render, screen, within } from '@testing-library/react';
import UpdatesPage from '@/app/(dashboard)/updates/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: () => ({
  data: { items: [{ id: 'device-ph006', name: 'PH006' }], total: 1 },
}) }));

beforeEach(() => jest.clearAllMocks());
afterEach(() => useAuthStore.setState({ user: null, sessionVersion: 0 }));

it('describes catalog-wide periodic delivery without offering a broken direct push', async () => {
  (api.get as jest.Mock).mockResolvedValue({ data: { releases: [{
    id: 'release-1', platform: 'android', flavor: 'dev', version_code: 10215,
    version_name: '1.2.15-dev', download_url: 'https://example.test/agent.apk',
    sha256: 'a'.repeat(64), mandatory: false, changelog: null,
    created_at: '2026-09-24T00:00:00Z',
  }], total: 1 } });

  render(<UpdatesPage />, { wrapper: createWrapper() });
  expect(await screen.findByText('v1.2.15-dev')).toBeInTheDocument();
  expect(screen.getByText(/только при совпадении платформы и варианта сборки/i)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'PH006' })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('shows canary releases in the default catalog view without implying normal agents poll them', async () => {
  (api.get as jest.Mock).mockResolvedValue({ data: { releases: [{
    id: 'canary-10228', platform: 'android-canary', flavor: 'dev', version_code: 10228,
    version_name: '1.2.28-dev', download_url: '/api/v1/updates/artifacts/' + 'b'.repeat(64),
    sha256: 'b'.repeat(64), mandatory: false, changelog: null,
    created_at: '2026-09-26T18:07:01Z',
  }], total: 1 } });

  render(<UpdatesPage />, { wrapper: createWrapper() });
  expect(await screen.findByText('v1.2.28-dev')).toBeInTheDocument();
  expect(screen.getByText(/обычные Android-агенты не проверяют его/i)).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/updates/?', { signal: expect.any(AbortSignal) });
});

it('reconciles an unknown removal by reading the catalog without replaying the delete', async () => {
  useAuthStore.setState({ user: { id: 'admin', org_id: 'tenant', email: 'admin@example.test', role: 'super_admin' } });
  const release = {
    id: 'release-1', platform: 'android', flavor: 'dev', version_code: 10215,
    version_name: '1.2.15-dev', download_url: 'https://example.test/agent.apk',
    sha256: 'a'.repeat(64), mandatory: false, changelog: null, created_at: '2026-09-24T00:00:00Z',
  };
  jest.mocked(api.get).mockResolvedValueOnce({ data: { releases: [release], total: 1 } })
    .mockResolvedValueOnce({ data: { releases: [], total: 0 } });
  jest.mocked(api.delete).mockRejectedValueOnce(new Error('transport lost'));
  render(<UpdatesPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Удалить релиз 1.2.15-dev · android/dev' }));
  const dialog = screen.getByRole('dialog');
  expect(dialog).toHaveTextContent('10215');
  expect(api.delete).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить удаление' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Результат удаления неизвестен');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Перечитать каталог' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Релиз 1.2.15-dev отсутствует');
  expect(api.delete).toHaveBeenCalledTimes(1);
});
