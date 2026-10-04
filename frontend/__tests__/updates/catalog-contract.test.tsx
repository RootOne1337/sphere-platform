import { render, screen } from '@testing-library/react';
import UpdatesPage from '@/app/(dashboard)/updates/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: () => ({
  data: { items: [{ id: 'device-ph006', name: 'PH006' }], total: 1 },
}) }));

it('describes catalog-wide periodic delivery without offering a broken direct push', async () => {
  (api.get as jest.Mock).mockResolvedValue({ data: { releases: [{
    id: 'release-1', platform: 'android', flavor: 'dev', version_code: 10215,
    version_name: '1.2.15-dev', download_url: 'https://example.test/agent.apk',
    sha256: 'a'.repeat(64), mandatory: false, changelog: null,
    created_at: '2026-09-24T00:00:00Z',
  }], total: 1 } });

  render(<UpdatesPage />, { wrapper: createWrapper() });
  expect(await screen.findByText('v1.2.15-dev')).toBeInTheDocument();
  expect(screen.getByText(/all agents of that flavor/i)).toBeInTheDocument();
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
  expect(screen.getByText(/normal Android agents do not poll this channel/i)).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/updates/?', { signal: expect.any(AbortSignal) });
});
