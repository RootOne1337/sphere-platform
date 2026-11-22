import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import GroupsPage from '@/app/(dashboard)/groups/page';
import LocationsPage from '@/app/(dashboard)/locations/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { createWrapper } from '../helpers';
import roles from '../fixtures/session-capabilities.json';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() } }));
jest.mock('@/src/features/access/Capabilities', () => ({ ...jest.requireActual('@/src/features/access/Capabilities'), useCapabilities: jest.fn(), PermissionNotice: () => null }));
const org = '22222222-2222-4222-8222-222222222222';
const id = '11111111-1111-4111-8111-111111111111';
const group = { id, org_id: org, name: 'Remote group', description: 'Original', color: '#123456', parent_group_id: null, total_devices: 2, online_devices: 1 };
const location = { ...group, name: 'Remote location', address: 'Old address', latitude: 0, longitude: 0,
  parent_location_id: null, created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-03T00:00:00Z' };
function access(grants: readonly string[], fields = {}) {
  jest.mocked(useCapabilities).mockReturnValue({ verified: true, pending: false, failed: false, role: 'fixture',
    can: permission => grants.includes(permission), canAccessRoute: () => true, retry: jest.fn(), ...fields });
}
beforeEach(() => {
  jest.clearAllMocks(); access(roles.org_admin);
  useAuthStore.setState({ accessToken: 'test', sessionVersion: 0, user: { id: 'actor', org_id: org, role: 'org_admin', email: 'a@example.org' } });
  jest.mocked(api.get).mockImplementation(async url => ({ data: url === '/groups' ? [group] : url === '/locations' ? [location] : location }) as never);
  jest.mocked(api.put).mockImplementation(async (url, patch) => ({ status: 200, data: { ...(url.startsWith('/groups') ? group : location), ...patch as object } }) as never);
  jest.mocked(api.post).mockImplementation(async (url, patch) => ({ status: 201, data: { ...(url === '/groups' ? group : location), ...patch as object } }) as never);
  jest.mocked(api.delete).mockResolvedValue({ status: 204 } as never);
});

it.each(['viewer', 'script_runner'] as const)('keeps groups readable without allowing mutations for %s', async role => {
  access(roles[role]); render(<GroupsPage />, { wrapper: createWrapper() });
  await screen.findByRole('heading', { name: group.name });
  for (const name of ['Создать группу', `Изменить группу ${group.name}`, `Удалить группу ${group.name}`]) {
    expect(screen.getByRole('button', { name })).toBeDisabled(); fireEvent.click(screen.getByRole('button', { name }));
  }
  expect(screen.getByRole('link', { name: `Устройства группы ${group.name}` })).toHaveAttribute('href', `/devices?group_id=${id}`);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled(); expect(api.delete).not.toHaveBeenCalled();
});

it('uses independent group write and delete authority', async () => {
  access(roles.device_manager); render(<GroupsPage />, { wrapper: createWrapper() });
  await screen.findByRole('heading', { name: group.name });
  expect(screen.getByRole('button', { name: 'Создать группу' })).toBeEnabled();
  expect(screen.getByRole('button', { name: `Изменить группу ${group.name}` })).toBeEnabled();
  expect(screen.getByRole('button', { name: `Удалить группу ${group.name}` })).toBeDisabled();
});

it.each(['pending', 'failed'] as const)('denies group writes while capabilities are %s despite a local admin role', async state => {
  access([], { verified: false, pending: state === 'pending', failed: state === 'failed' });
  render(<GroupsPage />, { wrapper: createWrapper() }); await screen.findByRole('heading', { name: group.name });
  expect(screen.getByRole('button', { name: 'Создать группу' })).toBeDisabled();
  expect(screen.getByRole('button', { name: `Удалить группу ${group.name}` })).toBeDisabled();
});

it.each(['create', 'edit'] as const)('blocks an open group %s form after received revocation, retaining its draft', async mode => {
  const view = render(<GroupsPage />, { wrapper: createWrapper() }); await screen.findByRole('heading', { name: group.name });
  fireEvent.click(screen.getByRole('button', { name: mode === 'create' ? 'Создать группу' : `Изменить группу ${group.name}` }));
  const dialog = screen.getByRole('dialog'); const input = within(dialog).getByRole('textbox', { name: 'Название' });
  fireEvent.change(input, { target: { value: 'Saved draft' } });
  access(roles.viewer); view.rerender(<GroupsPage />);
  const submit = within(dialog).getByRole('button', { name: mode === 'create' ? 'Создать группу' : 'Сохранить изменения' });
  expect(submit).toBeDisabled(); expect(input).toHaveValue('Saved draft');
  fireEvent.submit(input.closest('form')!); fireEvent.click(submit);
  expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled();
  expect(within(dialog).getByRole('button', { name: 'Отмена' })).toBeEnabled();
  access(roles.device_manager); view.rerender(<GroupsPage />);
  expect(submit).toBeEnabled(); fireEvent.submit(input.closest('form')!);
  await waitFor(() => expect(mode === 'create' ? api.post : api.put).toHaveBeenCalledTimes(1));
});

it('withdraws deletion from an already open group confirmation', async () => {
  const view = render(<GroupsPage />, { wrapper: createWrapper() }); await screen.findByRole('heading', { name: group.name });
  fireEvent.click(screen.getByRole('button', { name: `Удалить группу ${group.name}` }));
  access(roles.device_manager); view.rerender(<GroupsPage />);
  const confirm = within(screen.getByRole('dialog')).getByRole('button', { name: 'Удалить группу' });
  expect(confirm).toBeDisabled(); fireEvent.click(confirm); expect(api.delete).not.toHaveBeenCalled();
  expect(within(screen.getByRole('dialog')).getByRole('button', { name: 'Отмена' })).toBeEnabled();
});

it.each(['viewer', 'script_runner'] as const)('trusts verified location permissions over a stale local admin role for %s', async role => {
  access(roles[role]); render(<LocationsPage />, { wrapper: createWrapper() }); await screen.findByText(location.name);
  expect(screen.queryByRole('button', { name: 'Создать локацию' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: `Изменить локацию ${location.name}` })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: `Удалить локацию ${location.name}` })).not.toBeInTheDocument();
});

it('separates location write from delete authority', async () => {
  access(roles.device_manager); render(<LocationsPage />, { wrapper: createWrapper() }); await screen.findByText(location.name);
  expect(screen.getByRole('button', { name: 'Создать локацию' })).toBeEnabled();
  expect(screen.getByRole('button', { name: `Изменить локацию ${location.name}` })).toBeEnabled();
  expect(screen.queryByRole('button', { name: `Удалить локацию ${location.name}` })).not.toBeInTheDocument();
});

it.each(['pending', 'failed'] as const)('does not expose location mutations while capabilities are %s', async state => {
  access([], { verified: false, pending: state === 'pending', failed: state === 'failed' });
  render(<LocationsPage />, { wrapper: createWrapper() }); await screen.findByText(location.name);
  expect(screen.queryByRole('button', { name: 'Создать локацию' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: `Удалить локацию ${location.name}` })).not.toBeInTheDocument();
});

it.each(['create', 'edit', 'delete'] as const)('blocks an open location %s dialog when its authority is withdrawn', async mode => {
  const view = render(<LocationsPage />, { wrapper: createWrapper() }); await screen.findByText(location.name);
  const opener = mode === 'create' ? 'Создать локацию' : `${mode === 'edit' ? 'Изменить' : 'Удалить'} локацию ${location.name}`;
  fireEvent.click(screen.getByRole('button', { name: opener }));
  const dialog = screen.getByRole('dialog');
  if (mode === 'delete') await within(dialog).findByRole('button', { name: 'Подтвердить удаление' });
  else {
    await waitFor(() => expect(within(dialog).getByLabelText('Название')).toHaveValue(mode === 'create' ? '' : location.name));
    fireEvent.change(within(dialog).getByLabelText('Название'), { target: { value: 'Location draft' } });
  }
  const target = mode === 'delete' ? 'Подтвердить удаление' : mode === 'create' ? 'Создать локацию' : 'Сохранить изменения';
  await waitFor(() => expect(within(dialog).getByRole('button', { name: target })).toBeEnabled());
  access(mode === 'delete' ? roles.device_manager : roles.viewer); view.rerender(<LocationsPage />);
  expect(within(dialog).getByRole('button', { name: target })).toBeDisabled(); fireEvent.click(within(dialog).getByRole('button', { name: target }));
  expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled(); expect(api.delete).not.toHaveBeenCalled();
  if (mode !== 'delete') expect(within(dialog).getByLabelText('Название')).toHaveValue('Location draft');
  expect(within(dialog).getByRole('button', { name: 'Перечитать состояние' })).toBeEnabled();
});
