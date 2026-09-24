import { render, screen } from '@testing-library/react';
import UpdatesPage from '@/app/(dashboard)/updates/page';
import { api } from '@/lib/api';

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

  render(<UpdatesPage />);
  expect(await screen.findByText('v1.2.15-dev')).toBeInTheDocument();
  expect(screen.getByText(/all agents of that flavor/i)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'PH006' })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});
