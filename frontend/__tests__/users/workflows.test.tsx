import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import UsersPage from '@/app/(dashboard)/users/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { createTestQueryClient, createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn() } }));
const actor = { id: 'actor', org_id: 'org', email: 'owner@example.org', role: 'org_owner' };
const member = { id: 'member', org_id: 'org', email: 'member@example.org', role: 'viewer', is_active: true,
  mfa_enabled: false, last_login_at: null, created_at: '2026-10-02T00:00:00Z' };
const owner = { ...member, ...actor };
const catalog = { items: [owner, member], total: 2, page: 1, per_page: 50, pages: 1 };
beforeEach(() => {
  jest.resetAllMocks();
  useAuthStore.setState({ user: actor, sessionVersion: 1 });
  jest.mocked(api.get).mockResolvedValue({ data: catalog } as never);
  jest.mocked(api.post).mockResolvedValue({ data: { ...member, id: 'created', email: 'new@example.org' } } as never);
});
afterEach(() => useAuthStore.setState({ user: null, sessionVersion: 0 }));
async function openCreate() {
  await screen.findByText(member.email);
  fireEvent.click(screen.getByRole('button', { name: 'Добавить пользователя' }));
  fireEvent.change(screen.getByLabelText('Электронная почта'), { target: { value: 'new@example.org' } });
  fireEvent.change(screen.getByLabelText('Временный пароль'), { target: { value: 'test-password-2026' } });
}
function submitCreate() {
  const form = screen.getByRole('dialog').querySelector('form');
  expect(form).not.toBeNull();
  fireEvent.submit(form!);
}
async function proposeRole(email = member.email, role = 'device_manager') {
  const input = await screen.findByRole('combobox', { name: `Роль пользователя ${email}` });
  fireEvent.change(input, { target: { value: role } });
  const dialog = await screen.findByRole('dialog');
  expect(dialog).toHaveTextContent(email);
  return dialog;
}

it('uses native email validity and enforces the backend password bounds without sending', async () => {
  render(<UsersPage />, { wrapper: createWrapper() }); await openCreate();
  const email = screen.getByLabelText('Электронная почта');
  expect(email).toBeRequired();
  fireEvent.change(email, { target: { value: 'invalid-email' } }); submitCreate();
  expect(api.post).not.toHaveBeenCalled();
  fireEvent.change(email, { target: { value: 'new@example.org' } });
  fireEvent.change(screen.getByLabelText('Временный пароль'), { target: { value: 'short' } }); submitCreate();
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Временный пароль')).toHaveAttribute('aria-invalid', 'true');
});
it('places a 422 password error on the field without rendering the rejected password', async () => {
  jest.mocked(api.post).mockRejectedValue({ response: { status: 422, data: { detail: [
    { loc: ['body', 'password'], msg: 'String should have at least 8 characters', input: 'secret-do-not-render' },
  ] } } });
  render(<UsersPage />, { wrapper: createWrapper() }); await openCreate(); submitCreate();
  await waitFor(() => expect(screen.getByLabelText('Временный пароль')).toHaveAttribute('aria-invalid', 'true'));
  expect(screen.getByLabelText('Временный пароль')).toHaveFocus();
  expect(screen.getByLabelText('Временный пароль')).toHaveValue('test-password-2026');
  expect(screen.getByRole('dialog')).not.toHaveTextContent('secret-do-not-render');
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('maps a duplicate email to the email field and retains the draft', async () => {
  jest.mocked(api.post).mockRejectedValue({ response: { status: 409, data: { detail: 'User with this email already exists' } } });
  render(<UsersPage />, { wrapper: createWrapper() }); await openCreate(); submitCreate();
  await waitFor(() => expect(screen.getByLabelText('Электронная почта')).toHaveAttribute('aria-invalid', 'true'));
  expect(screen.getByLabelText('Электронная почта')).toHaveFocus();
  expect(screen.getByLabelText('Электронная почта')).toHaveValue('new@example.org');
});
it('identifies a forbidden assignment on the role field and never automatically retries', async () => {
  const client = createTestQueryClient(); client.setDefaultOptions({ mutations: { retry: 2, retryDelay: 1 } });
  jest.mocked(api.post).mockRejectedValue({ response: { status: 403, data: { detail: 'Cannot assign this role' } } });
  render(<UsersPage />, { wrapper: createWrapper(client) }); await openCreate(); submitCreate();
  await waitFor(() => expect(screen.getByLabelText('Роль')).toHaveAttribute('aria-invalid', 'true'));
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('keeps a create form open when the server acknowledges a different account', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: member } as never);
  render(<UsersPage />, { wrapper: createWrapper() }); await openCreate(); submitCreate();
  expect(await screen.findByRole('alert')).toHaveTextContent('не подтверждён');
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
it('confirms a role change explicitly and retains the original role on rejection', async () => {
  jest.mocked(api.put).mockRejectedValue({ response: { status: 400, data: { detail: 'Cannot remove the last org_owner' } } });
  render(<UsersPage />, { wrapper: createWrapper() });
  const dialog = await proposeRole(actor.email, 'viewer');
  expect(api.put).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Изменить роль' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('последнего владельца');
  expect(screen.getByLabelText(`Роль пользователя ${actor.email}`)).toHaveValue('org_owner');
  expect(api.put).toHaveBeenCalledTimes(1);
});
it('does not claim success for an ignored role change or wrong response owner', async () => {
  jest.mocked(api.put).mockResolvedValue({ data: { ...member, id: 'another', role: 'device_manager' } } as never);
  render(<UsersPage />, { wrapper: createWrapper() }); const dialog = await proposeRole();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Изменить роль' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('не подтверждён');
  expect(screen.getByLabelText(`Роль пользователя ${member.email}`)).toHaveValue('viewer');
});
it('requires an exact deactivate receipt and names the rejected target', async () => {
  jest.mocked(api.patch).mockResolvedValue({ status: 200, data: null } as never);
  render(<UsersPage />, { wrapper: createWrapper() }); await screen.findByText(member.email);
  const row = screen.getByText(member.email).closest('tr')!;
  fireEvent.click(within(row).getByRole('button', { name: 'Отключить' }));
  const dialog = screen.getByRole('dialog');
  expect(dialog).toHaveTextContent(member.email);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Отключить пользователя' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('не подтверждён');
  expect(within(row).getByText('Активен')).toBeInTheDocument();
});
it('respects actual org_admin grant restrictions, API-user roles and self deactivation', async () => {
  useAuthStore.setState({ user: { ...actor, role: 'org_admin' } });
  render(<UsersPage />, { wrapper: createWrapper() }); await openCreate();
  const role = screen.getByLabelText('Роль');
  expect(within(role).queryByRole('option', { name: 'Владелец организации' })).not.toBeInTheDocument();
  expect(within(role).queryByRole('option', { name: 'Администратор' })).not.toBeInTheDocument();
  expect(within(role).getByRole('option', { name: 'API-пользователь' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
  expect(screen.getByRole('combobox', { name: `Роль пользователя ${member.email}` })).toBeDisabled();
  expect(within(screen.getByText(actor.email).closest('tr')!).getByRole('button', { name: 'Отключить' })).toBeDisabled();
});
it('blocks writes while pending and does not discard the submitted create draft', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.post).mockReturnValue(new Promise(r => { resolve = r; }) as never);
  render(<UsersPage />, { wrapper: createWrapper() }); await openCreate(); submitCreate();
  await waitFor(() => expect(screen.getByLabelText('Электронная почта')).toBeDisabled());
  expect(screen.getByRole('button', { name: 'Отмена' })).toBeDisabled();
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  submitCreate(); expect(api.post).toHaveBeenCalledTimes(1);
  await act(async () => resolve({ data: { ...member, id: 'created', email: 'new@example.org' } }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});
it('hides user controls when a cached catalog fails its refresh', async () => {
  const client = createTestQueryClient();
  render(<UsersPage />, { wrapper: createWrapper(client) }); await screen.findByText(member.email);
  jest.mocked(api.get).mockRejectedValue({ response: { status: 403 } });
  await act(async () => { await client.invalidateQueries({ queryKey: ['users'] }); });
  await waitFor(() => expect(screen.queryByRole('combobox', { name: `Роль пользователя ${member.email}` })).not.toBeInTheDocument());
  expect(screen.getByRole('button', { name: 'Добавить пользователя' })).toBeDisabled();
});

it('confirms create and clears the password when the dialog is reopened', async () => {
  render(<UsersPage />, { wrapper: createWrapper() }); await openCreate(); submitCreate();
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('status')).toHaveTextContent('new@example.org');
  fireEvent.click(screen.getByRole('button', { name: 'Добавить пользователя' }));
  expect(screen.getByLabelText('Временный пароль')).toHaveValue('');
});
it('does not accept a create receipt belonging to a different organization', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { ...member, id: 'new', email: 'new@example.org', org_id: 'foreign' } } as never);
  render(<UsersPage />, { wrapper: createWrapper() }); await openCreate(); submitCreate();
  expect(await screen.findByRole('alert')).toHaveTextContent('не подтверждён');
});
it('reconciles a confirmed role receipt and reports the exact target', async () => {
  jest.mocked(api.put).mockImplementation(async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { ...catalog, items: [owner, { ...member, role: 'device_manager' }] } } as never);
    return { data: { ...member, role: 'device_manager' } } as never;
  });
  render(<UsersPage />, { wrapper: createWrapper() }); const dialog = await proposeRole();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Изменить роль' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('status')).toHaveTextContent(member.email);
  expect(screen.getByRole('combobox', { name: `Роль пользователя ${member.email}` })).toHaveValue('device_manager');
});
it('confirms deactivate only after 204 and the refreshed catalog shows inactive', async () => {
  jest.mocked(api.patch).mockImplementation(async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { ...catalog, items: [owner, { ...member, is_active: false }] } } as never);
    return { status: 204, data: '' } as never;
  });
  render(<UsersPage />, { wrapper: createWrapper() }); await screen.findByText(member.email);
  fireEvent.click(within(screen.getByText(member.email).closest('tr')!).getByRole('button', { name: 'Отключить' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Отключить пользователя' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByRole('status')).toHaveTextContent(member.email);
  expect(within(screen.getByText(member.email).closest('tr')!).getByText('Отключён')).toBeInTheDocument();
});
it('retires a pending create when the signed-in identity changes', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.post).mockReturnValue(new Promise(r => { resolve = r; }) as never);
  render(<UsersPage />, { wrapper: createWrapper() }); await openCreate(); submitCreate();
  act(() => useAuthStore.setState({ user: { ...actor, id: 'new-actor', role: 'viewer' }, sessionVersion: 2 }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  await act(async () => resolve({ data: { ...member, id: 'created', email: 'new@example.org' } }));
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Нет доступа');
});
