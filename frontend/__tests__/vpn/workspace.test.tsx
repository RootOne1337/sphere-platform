import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VPNManagerPage from '@/app/(dashboard)/vpn/page';
import { useAuthStore } from '@/lib/store';

jest.mock('@/src/features/vpn/AppVpnRuntimePanel', () => ({ AppVpnRuntimePanel: () => <p>Android runtime fixture</p> }));
jest.mock('@/src/features/vpn/VpnProfileCatalog', () => ({ VpnProfileCatalog: () => <p>Profile catalog fixture</p> }));
jest.mock('@/src/features/vpn/VpnRouterInfrastructure', () => ({ VpnRouterInfrastructure: () => <p>Router fixture</p> }));
jest.mock('@/src/features/vpn/VpnProfileInspector', () => ({ VpnProfileInspector: ({ purpose }: { purpose?: string }) => <p>{purpose === 'save' ? 'Import fixture' : 'Inspect fixture'}</p> }));
beforeEach(() => useAuthStore.setState({ user: { id: 'actor', org_id: 'org', role: 'org_admin', email: 'fixture@example.org' }, sessionVersion: 1 }));
it('opens Android connections first and keeps infrastructure separate', async () => {
  render(<VPNManagerPage />);
  expect(screen.getByRole('tab', { name: 'Подключения' })).toHaveAttribute('data-state', 'active');
  expect(screen.getByText('Android runtime fixture')).toBeInTheDocument();
  expect(screen.queryByText('Router fixture')).not.toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole('tab', { name: 'Профили' }));
  expect(screen.getByText('Profile catalog fixture')).toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole('tab', { name: 'Политика трафика' }));
  expect(screen.getByRole('region', { name: 'Принцип маршрутизации VPN' })).toBeInTheDocument();
});
it('exposes import only to the write role', async () => {
  const shown = render(<VPNManagerPage />);
  await userEvent.setup().click(screen.getByRole('button', { name: 'Импорт .conf' }));
  expect(screen.getByText('Import fixture')).toBeInTheDocument();
  shown.unmount();
  useAuthStore.setState({ user: { id: 'viewer', org_id: 'org', role: 'viewer', email: 'viewer@example.org' }, sessionVersion: 2 });
  render(<VPNManagerPage />);
  expect(screen.queryByRole('button', { name: 'Импорт .conf' })).not.toBeInTheDocument();
  expect(screen.queryByText('Import fixture')).not.toBeInTheDocument();
});
