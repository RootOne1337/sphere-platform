import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import GroupsPage from '@/app/(dashboard)/groups/page';
import { api } from '@/lib/api';
import { createTestQueryClient, createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() } }));
const root = { id: 'root', org_id: 'org', name: 'Root', description: null, color: null,
  parent_group_id: null, total_devices: 0, online_devices: 0 };
const child = { ...root, id: 'child', name: 'Child', parent_group_id: root.id };
const leaf = { ...root, id: 'leaf', name: 'Leaf', parent_group_id: child.id };
const independent = { ...root, id: 'independent', name: 'Independent' };
beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(api.get).mockResolvedValue({ data: [root, child, leaf, independent] } as never);
  jest.mocked(api.put).mockImplementation(async (_url, body) => ({ data: { ...child, ...body as object } } as never));
});
async function edit(name = 'Child') {
  await screen.findByRole('heading', { name });
  fireEvent.click(screen.getByRole('button', { name: `Изменить группу ${name}` }));
}
function save() { fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' })); }

it('clears the captured parent explicitly and confirms the null response', async () => {
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit();
  expect(screen.getByRole('combobox', { name: 'Родительская группа' })).toHaveValue(root.id);
  fireEvent.change(screen.getByRole('combobox', { name: 'Родительская группа' }), { target: { value: '' } }); save();
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/groups/child', { parent_group_id: null }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});
it('excludes self and descendants from allowed parent choices', async () => {
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit('Root');
  const select = screen.getByRole('combobox', { name: 'Родительская группа' });
  expect(within(select).queryByRole('option', { name: 'Root' })).not.toBeInTheDocument();
  expect(within(select).queryByRole('option', { name: 'Child' })).not.toBeInTheDocument();
  expect(within(select).queryByRole('option', { name: 'Leaf' })).not.toBeInTheDocument();
  expect(within(select).getByRole('option', { name: 'Independent' })).toBeInTheDocument();
});
it('changes only the selected parent and retains the draft after a server conflict', async () => {
  jest.mocked(api.put).mockRejectedValue({ response: { status: 409, data: { detail: 'Refresh and retry' } } });
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit();
  fireEvent.change(screen.getByRole('combobox', { name: 'Родительская группа' }), { target: { value: independent.id } }); save();
  expect(await screen.findByRole('alert')).toHaveTextContent('Refresh and retry');
  expect(api.put).toHaveBeenCalledTimes(1);
  expect(api.put).toHaveBeenCalledWith('/groups/child', { parent_group_id: independent.id });
  expect(screen.getByRole('combobox', { name: 'Родительская группа' })).toHaveValue(independent.id);
});
it('rejects a successful status that failed to clear the relationship', async () => {
  jest.mocked(api.put).mockResolvedValue({ data: child } as never);
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit();
  fireEvent.change(screen.getByRole('combobox', { name: 'Родительская группа' }), { target: { value: '' } }); save();
  expect(await screen.findByRole('alert')).toHaveTextContent('не подтверждён');
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
it('creates a child with its selected parent', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { ...root, name: 'New', parent_group_id: root.id } } as never);
  render(<GroupsPage />, { wrapper: createWrapper() }); await screen.findByRole('heading', { name: 'Root' });
  fireEvent.click(screen.getByRole('button', { name: 'Создать группу' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.change(within(dialog).getByRole('textbox', { name: 'Название' }), { target: { value: 'New' } });
  fireEvent.change(within(dialog).getByRole('combobox', { name: 'Родительская группа' }), { target: { value: root.id } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Создать группу' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/groups', { name: 'New', description: undefined, color: '#3B82F6', parent_group_id: root.id }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});
it('does not confirm creation when the server ignored the chosen parent', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { ...root, name: 'New' } } as never);
  render(<GroupsPage />, { wrapper: createWrapper() }); await screen.findByRole('heading', { name: 'Root' });
  fireEvent.click(screen.getByRole('button', { name: 'Создать группу' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.change(within(dialog).getByRole('textbox', { name: 'Название' }), { target: { value: 'New' } });
  fireEvent.change(within(dialog).getByRole('combobox', { name: 'Родительская группа' }), { target: { value: root.id } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Создать группу' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('не подтверждён');
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
it('does not silently clear a vanished parent after catalog refresh', async () => {
  const client = createTestQueryClient();
  render(<GroupsPage />, { wrapper: createWrapper(client) }); await edit();
  fireEvent.change(screen.getByRole('textbox', { name: 'Название' }), { target: { value: 'Draft' } });
  act(() => client.setQueryData(['groups'], [child, leaf, independent]));
  expect(await screen.findByRole('alert')).toHaveTextContent('Родительская связь недоступна');
  expect(screen.getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled();
  expect(api.put).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('combobox', { name: 'Родительская группа' }), { target: { value: '' } }); save();
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/groups/child', { name: 'Draft', parent_group_id: null }));
});
it('excludes corrupted ancestry without recursion and permits explicit repair', async () => {
  const corrupted = { ...root, parent_group_id: child.id };
  jest.mocked(api.get).mockResolvedValue({ data: [corrupted, child, leaf, independent] } as never);
  jest.mocked(api.put).mockImplementation(async (_url, body) => ({ data: { ...corrupted, ...body as object } } as never));
  render(<GroupsPage />, { wrapper: createWrapper() }); await edit('Root');
  expect(screen.getByRole('alert')).toHaveTextContent('Родительская связь недоступна');
  const select = screen.getByRole('combobox', { name: 'Родительская группа' });
  expect(within(select).queryByRole('option', { name: 'Leaf' })).not.toBeInTheDocument();
  fireEvent.change(select, { target: { value: '' } }); save();
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/groups/root', { parent_group_id: null }));
});
