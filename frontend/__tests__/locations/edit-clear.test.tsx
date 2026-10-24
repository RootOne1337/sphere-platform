import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LocationsPage from '@/app/(dashboard)/locations/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';
import { useAuthStore } from '@/lib/store';

import rolePermissions from '../fixtures/session-capabilities.json';

jest.mock('@/src/features/access/Capabilities', () => ({ ...jest.requireActual('@/src/features/access/Capabilities'),
  // Notice/provider rendering has separate real-provider tests; this fixture isolates the workflow authority.
  PermissionNotice: () => null,
  useCapabilities: () => ({ verified: true, pending: false, failed: false, can: (permission: string) => ((rolePermissions[useAuthStore.getState().user?.role as keyof typeof rolePermissions] ?? []) as readonly string[]).includes(permission) }),
}));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), put: jest.fn() } }));

it('sends explicit null when clearing an existing location and shows the confirmed empty values', async () => {
  const org = '22222222-2222-4222-8222-222222222222';
  const id = '11111111-1111-4111-8111-111111111111';
  useAuthStore.setState({ user: { id: 'actor', org_id: org, email: 'a@example.org', role: 'org_admin' }, sessionVersion: 0 });
  let location = { id, org_id: org, name: 'Remote', description: 'Old description', address: 'Old address', color: '#3b82f6', latitude: null, longitude: null, parent_location_id: null,
    created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-03T00:00:00Z', total_devices: 2, online_devices: 1 };
  jest.mocked(api.get).mockImplementation(async url => ({ data: url === '/locations' ? [location] : location }) as never);
  jest.mocked(api.put).mockImplementation(async (_, updates) => {
    location = { ...location, ...(updates as Partial<typeof location>) };
    return { status: 200, data: location } as never;
  });
  render(<LocationsPage />, { wrapper: createWrapper() });
  await userEvent.click(await screen.findByRole('button', { name: 'Изменить локацию Remote' }));
  await screen.findByLabelText('Адрес');
  fireEvent.change(screen.getByLabelText(/Описание/), { target: { value: '   ' } });
  fireEvent.change(screen.getByLabelText('Адрес'), { target: { value: '' } });
  await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/locations/' + id, {
    description: null, address: null, expected_updated_at: '2026-10-03T00:00:00Z',
  }));
  expect(await screen.findByText('Адрес не указан')).toBeInTheDocument();
  expect(screen.getByText('Описание не добавлено')).toBeInTheDocument();
});
