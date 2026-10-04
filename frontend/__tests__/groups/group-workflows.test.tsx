import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import GroupsPage from '@/app/(dashboard)/groups/page';
import { api } from '@/lib/api';
import { createTestQueryClient, createWrapper } from '../helpers';

import rolePermissions from '../fixtures/session-capabilities.json';

jest.mock('@/src/features/access/Capabilities', () => ({ ...jest.requireActual('@/src/features/access/Capabilities'),
  // Notice/provider rendering has separate real-provider tests; this fixture isolates the workflow authority.
  PermissionNotice: () => null,
  useCapabilities: () => ({ verified: true, pending: false, failed: false, can: (permission: string) => rolePermissions.org_admin.includes(permission) }),
}));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() } }));
const group = { id: '00000000-0000-4000-8000-000000000001', org_id: 'org', name: 'Remote', description: 'Original',
  color: '#123456', parent_group_id: null, total_devices: 12, online_devices: 9 };
const other = { ...group, id: '00000000-0000-4000-8000-000000000002', name: 'Local' };
beforeEach(() => {
  jest.resetAllMocks();
  window.confirm = jest.fn(() => false);
  jest.mocked(api.get).mockResolvedValue({ data: [group, other] } as never);
  jest.mocked(api.put).mockImplementation(async (_url, body) => ({ data: { ...group, ...body as object } } as never));
  jest.mocked(api.delete).mockResolvedValue({ status: 204 } as never);
});
afterEach(() => jest.useRealTimers());
async function edit() {
  await screen.findByRole('heading', { name: 'Remote' });
  fireEvent.click(screen.getByRole('button', { name: 'Изменить группу Remote' }));
}
function save() { fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' })); }

it('reads groups without dispatching a mutation', async () => {
  render(<GroupsPage />, { wrapper: createWrapper() });
  await screen.findByRole('heading', { name: 'Remote' });
  expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled(); expect(api.delete).not.toHaveBeenCalled();
});
it('opens the existing device registry with the server group ID rather than a group name', async () => {
  render(<GroupsPage />, { wrapper: createWrapper() });
  expect(await screen.findByRole('link', { name: 'Устройства группы Remote' })).toHaveAttribute('href', `/devices?group_id=${group.id}`);
});
it('saves trimmed metadata and explicitly clears a description without rewriting untouched fields', async () => {
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit();
  fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: ' Remote Europe ' } });
  fireEvent.change(screen.getByRole('textbox', { name: /Описание/ }), { target: { value: '   ' } }); save();
  await waitFor(() => expect(api.put).toHaveBeenCalledWith(`/groups/${group.id}`, { name: 'Remote Europe', description: '' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('status')).toHaveTextContent('Группа обновлена');
});
it('preserves null color when only the name changes', async () => {
  jest.mocked(api.get).mockResolvedValue({ data: [{ ...group, color: null }] } as never);
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit();
  fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: 'Renamed' } }); save();
  await waitFor(() => expect(api.put).toHaveBeenCalledWith(`/groups/${group.id}`, { name: 'Renamed' }));
});
it('does not overwrite a dirty draft when group statistics refresh', async () => {
  const client = createTestQueryClient(); render(<GroupsPage />, { wrapper: createWrapper(client) }); await edit();
  fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: 'Draft' } });
  await act(async () => { client.setQueryData(['groups'], [{ ...group, name: 'Server changed', online_devices: 8 }, other]); });
  expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Draft'); save();
  await waitFor(() => expect(api.put).toHaveBeenCalledWith(`/groups/${group.id}`, { name: 'Draft' }));
});
it.each([409, 403])('keeps entered data and exposes the server explanation for %s', async (status) => {
  jest.mocked(api.put).mockRejectedValue({ response: { status, data: { detail: status === 409 ? 'Name already exists' : 'Forbidden' } } });
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit();
  fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: 'Draft' } }); save();
  expect(await screen.findByRole('alert')).toHaveTextContent(status === 409 ? 'Name already exists' : 'Forbidden');
  expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Draft');
  expect(screen.queryByText('Группа обновлена')).not.toBeInTheDocument();
});
it('blocks empty, oversized and unchanged updates', async () => {
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit();
  expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled();
  for (const name of ['   ', 'x'.repeat(256)]) {
    fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: name } });
    expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled(); save();
  }
  expect(api.put).not.toHaveBeenCalled();
});
it('does not dispatch an edit after the selected group disappears from the current catalog', async () => {
  const client = createTestQueryClient(); render(<GroupsPage />, { wrapper: createWrapper(client) }); await edit();
  fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: 'Draft' } });
  await act(async () => { client.setQueryData(['groups'], [other]); });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled()); save();
  expect(api.put).not.toHaveBeenCalled();
});
it('cannot close or submit the editor twice while its captured request is pending', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.put).mockImplementation(() => new Promise((done) => { resolve = done; }) as never);
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit();
  fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: 'Draft' } }); save(); save();
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  await act(async () => { resolve({ data: { ...group, name: 'Draft' } }); });
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});
it('explains membership loss and deletes only the confirmed group, invalidating device memberships too', async () => {
  const client = createTestQueryClient(); const invalidate = jest.spyOn(client, 'invalidateQueries');
  render(<GroupsPage />, { wrapper: createWrapper(client) }); await screen.findByRole('heading', { name: 'Remote' });
  fireEvent.click(screen.getByRole('button', { name: 'Удалить группу Remote' }));
  const dialog = screen.getByRole('dialog');
  expect(dialog).toHaveTextContent('12 устройств'); expect(dialog).toHaveTextContent('Членство в этой группе будет удалено');
  expect(api.delete).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Удалить группу' }));
  await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/groups/${group.id}`));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['devices'] });
});
it('does not report a successful update if the API answers for a different group', async () => {
  jest.mocked(api.put).mockResolvedValue({ data: other } as never);
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit();
  fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: 'Draft' } }); save();
  expect(await screen.findByRole('alert')).toHaveTextContent('не подтверждён');
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
it('does not report success if the correct owner response ignores the requested metadata', async () => {
  jest.mocked(api.put).mockResolvedValue({ data: group } as never);
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit();
  fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: 'Draft' } }); save();
  expect(await screen.findByRole('alert')).toHaveTextContent('не подтверждён');
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
it('does not convert a failed group read into an empty catalog or enable catalog writes', async () => {
  jest.mocked(api.get).mockRejectedValue(new Error('network unavailable'));
  render(<GroupsPage />, { wrapper: createWrapper() });
  await screen.findByText('Не удалось загрузить группы');
  expect(screen.queryByText('Групп пока нет')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Создать группу' })).toBeDisabled();
});
it('does not inherit automatic mutation retries after an uncertain response', async () => {
  jest.useFakeTimers();
  const client = createTestQueryClient(); client.setDefaultOptions({ ...client.getDefaultOptions(), mutations: { retry: 3, retryDelay: 1 } });
  jest.mocked(api.put).mockRejectedValue(new Error('response lost'));
  render(<GroupsPage />, { wrapper: createWrapper(client) });
  await act(async () => { await jest.advanceTimersByTimeAsync(20); }); await edit();
  fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: 'Draft' } }); save();
  await act(async () => { await jest.advanceTimersByTimeAsync(100); });
  expect(api.put).toHaveBeenCalledTimes(1); expect(screen.getByRole('alert')).toBeInTheDocument();
});

it('creates a group with bounded trimmed fields and confirms the returned server record', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { ...group, name: 'New' } } as never);
  render(<GroupsPage />, { wrapper: createWrapper() }); await screen.findByRole('heading', { name: 'Remote' });
  fireEvent.click(screen.getByRole('button', { name: 'Создать группу' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.change(within(dialog).getByRole('textbox', { name: 'Название' }), { target: { value: ' New ' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Создать группу' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/groups', { name: 'New', description: undefined, color: '#3B82F6' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('status')).toHaveTextContent('Группа создана');
});
it('keeps the confirmed deletion owner and reports a forbidden response', async () => {
  jest.mocked(api.delete).mockRejectedValue({ response: { status: 403, data: { detail: 'Forbidden' } } });
  render(<GroupsPage />, { wrapper: createWrapper() }); await screen.findByRole('heading', { name: 'Remote' });
  fireEvent.click(screen.getByRole('button', { name: 'Удалить группу Remote' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Удалить группу' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
  expect(screen.getByRole('dialog')).toHaveTextContent(group.id);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});
it('rejects an unconfirmed deletion response instead of claiming success', async () => {
  jest.mocked(api.delete).mockResolvedValue({ status: 200, data: {} } as never);
  render(<GroupsPage />, { wrapper: createWrapper() }); await screen.findByRole('heading', { name: 'Remote' });
  fireEvent.click(screen.getByRole('button', { name: 'Удалить группу Remote' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Удалить группу' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('не подтверждён');
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
it('rejects a malformed catalog row before exposing operations', async () => {
  jest.mocked(api.get).mockResolvedValue({ data: [{ ...group, total_devices: null }] } as never);
  render(<GroupsPage />, { wrapper: createWrapper() }); await screen.findByText('Не удалось загрузить группы');
  expect(screen.queryByRole('heading', { name: 'Remote' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Создать группу' })).toBeDisabled();
});
it('allows changing the label color without overwriting membership or metadata', async () => {
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit();
  fireEvent.change(screen.getByLabelText('Цвет метки'), { target: { value: '#abcdef' } }); save();
  await waitFor(() => expect(api.put).toHaveBeenCalledWith(`/groups/${group.id}`, { color: '#abcdef' }));
});
it('blocks an open editor after a background read fails and retains the draft for recovery', async () => {
  const client = createTestQueryClient(); render(<GroupsPage />, { wrapper: createWrapper(client) }); await edit();
  fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: 'Draft' } });
  jest.mocked(api.get).mockRejectedValue(new Error('offline'));
  await act(async () => { await client.invalidateQueries({ queryKey: ['groups'] }); });
  await screen.findByText('Не удалось загрузить группы');
  expect(screen.getByRole('textbox', { name: 'Название' })).toHaveValue('Draft');
  expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled(); save();
  expect(api.put).not.toHaveBeenCalled();
});
