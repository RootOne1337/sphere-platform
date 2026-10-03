import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import LocationsPage from '@/app/(dashboard)/locations/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { createTestQueryClient, createWrapper } from '../helpers';
import { emptyLocationDraft, locationDraft, parentChoices, validateLocationDraft, verifyLocationReceipt } from '@/src/features/locations/locationContract';
import type { Location } from '@/lib/hooks/useLocations';

import rolePermissions from '../fixtures/session-capabilities.json';

jest.mock('@/src/features/access/Capabilities', () => ({ ...jest.requireActual('@/src/features/access/Capabilities'),
  // Notice/provider rendering has separate real-provider tests; this fixture isolates the workflow authority.
  PermissionNotice: () => null,
  useCapabilities: () => ({ verified: true, pending: false, failed: false, can: (permission: string) => ((rolePermissions[useAuthStore.getState().user?.role as keyof typeof rolePermissions] ?? []) as readonly string[]).includes(permission) }),
}));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() } }));
const org = '22222222-2222-4222-8222-222222222222';
const id = '11111111-1111-4111-8111-111111111111';
const childId = '33333333-3333-4333-8333-333333333333';
const original = (): Location => ({ id, org_id: org, name: 'Remote', description: 'Original', address: 'Old address', color: '#3b82f6', latitude: 0, longitude: 180,
  parent_location_id: null, created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-03T00:00:00Z', total_devices: 2, online_devices: 1 });
let location: Location;
let catalog: Location[];
beforeEach(() => {
  jest.resetAllMocks(); location = original(); catalog = [location, { ...location, id: childId, name: 'Room', parent_location_id: id }];
  useAuthStore.setState({ accessToken: 'test', sessionVersion: 0, user: { id: 'actor', org_id: org, role: 'org_admin', email: 'a@example.org' } });
  jest.mocked(api.get).mockImplementation(async url => ({ data: url === '/locations' ? catalog : location }) as never);
  jest.mocked(api.put).mockImplementation(async (_, patch) => {
    const { expected_updated_at: _condition, ...fields } = patch as Location & { expected_updated_at?: string };
    location = { ...location, ...fields, updated_at: '2026-10-03T00:01:00Z' }; catalog[0] = location;
    return { status: 200, data: location } as never;
  });
});
async function open() {
  const qc = createTestQueryClient(); render(<LocationsPage />, { wrapper: createWrapper(qc) });
  fireEvent.click(await screen.findByRole('button', { name: 'Изменить локацию Remote' }));
  const dialog = await screen.findByRole('dialog');
  await waitFor(() => expect(within(dialog).getByLabelText('Широта')).toHaveValue('0'));
  return { dialog, qc };
}
it('reads owned detail, shows zero coordinates and excludes self and descendants from parents', async () => {
  const { dialog } = await open();
  expect(api.get).toHaveBeenCalledWith('/locations/' + id, { signal: expect.any(AbortSignal) });
  expect(within(dialog).getByLabelText('Долгота')).toHaveValue('180');
  expect(within(dialog).getByLabelText('Родительская локация')).toHaveValue('');
  expect(within(dialog).queryByRole('option', { name: 'Remote' })).not.toBeInTheDocument();
  expect(within(dialog).queryByRole('option', { name: /Room/ })).not.toBeInTheDocument();
});
it('clears coordinates with null and saves only changed fields with a revision', async () => {
  const { dialog } = await open();
  fireEvent.change(within(dialog).getByLabelText('Широта'), { target: { value: '' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить изменения' }));
  await within(dialog).findByText(/Сохранение подтверждено API/);
  expect(api.put).toHaveBeenCalledWith('/locations/' + id, { latitude: null, expected_updated_at: original().updated_at });
});
it.each([403, 404, 409, 422])('retains dirty fields and blocks repeated write after %i', async status => {
  const { dialog } = await open();
  fireEvent.change(within(dialog).getByLabelText('Адрес'), { target: { value: 'Changed' } });
  jest.mocked(api.put).mockRejectedValue({ response: { status, data: { detail: 'private error' } } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить изменения' }));
  await within(dialog).findByRole('alert');
  expect(within(dialog).getByLabelText('Адрес')).toHaveValue('Changed');
  expect(within(dialog).getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled();
  expect(dialog.textContent).not.toContain('private error'); expect(api.put).toHaveBeenCalledTimes(1);
});
it('rejects invalid latitude before HTTP', async () => {
  const { dialog } = await open();
  fireEvent.change(within(dialog).getByLabelText('Широта'), { target: { value: '91' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить изменения' }));
  await within(dialog).findByText(/Широта: число/); expect(api.put).not.toHaveBeenCalled();
});
it('does not trust a receipt belonging to another organization', async () => {
  const { dialog } = await open();
  fireEvent.change(within(dialog).getByLabelText('Адрес'), { target: { value: 'Changed' } });
  jest.mocked(api.put).mockResolvedValue({ status: 200, data: { ...location, address: 'Changed', org_id: childId } } as never);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить изменения' }));
  await within(dialog).findByText(/Результат записи неизвестен/);
  expect(within(dialog).queryByText(/Сохранение подтверждено/)).not.toBeInTheDocument();
});
it('unknown network outcome is never automatically replayed', async () => {
  const { dialog } = await open();
  fireEvent.change(within(dialog).getByLabelText('Адрес'), { target: { value: 'Changed' } });
  jest.mocked(api.put).mockRejectedValue(new Error('timeout'));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить изменения' }));
  await within(dialog).findByText(/Результат записи неизвестен/); expect(api.put).toHaveBeenCalledTimes(1);
});
it('viewer has read-only geography with no mutation controls', async () => {
  useAuthStore.setState({ user: { ...useAuthStore.getState().user!, role: 'viewer' } });
  render(<LocationsPage />, { wrapper: createWrapper() });
  await screen.findByText('Remote');
  expect(screen.queryByRole('button', { name: 'Создать локацию' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Изменить локацию Remote' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Удалить локацию Remote' })).not.toBeInTheDocument();
});
it('session replacement closes a prior organization draft', async () => {
  const { dialog } = await open();
  fireEvent.change(within(dialog).getByLabelText('Адрес'), { target: { value: 'Secret draft' } });
  act(() => useAuthStore.setState({ sessionVersion: 1, user: { ...useAuthStore.getState().user!, org_id: childId } }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument()); expect(api.put).not.toHaveBeenCalled();
});
it.each(['NaN', 'Infinity', '0x10', '90.001'])('validates latitude text %s without coercing invalid input', value => {
  expect(() => validateLocationDraft({ ...locationDraft(location), latitude: value }, catalog, location)).toThrow(/Широта/);
});
it('new form supports the equator, meridian and a root parent', () => {
  expect(validateLocationDraft({ ...emptyLocationDraft(), name: 'New', latitude: '0', longitude: '0' }, catalog)).toMatchObject({ latitude: 0, longitude: 0, parent_location_id: null });
});
it('does not offer corrupt ancestry as a parent', () => {
  const bad = [{ ...location, parent_location_id: childId }, catalog[1]];
  expect(parentChoices(bad)).toHaveLength(0);
  expect(parentChoices(catalog, id)).toHaveLength(0);
});
it('refuses an unchanged response to a changed field', () => {
  expect(() => verifyLocationReceipt(location, org, { address: 'Changed' }, location)).toThrow();
});

it('creates with a real parent and valid boundary coordinates', async () => {
  render(<LocationsPage />, { wrapper: createWrapper() });
  const button = await screen.findByRole('button', { name: 'Создать локацию' });
  await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
  const dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText('Название'), { target: { value: 'New room' } });
  fireEvent.change(within(dialog).getByLabelText('Широта'), { target: { value: '-90' } });
  fireEvent.change(within(dialog).getByLabelText('Долгота'), { target: { value: '0' } });
  fireEvent.change(within(dialog).getByLabelText('Родительская локация'), { target: { value: id } });
  jest.mocked(api.post).mockImplementation(async (_, data) => ({ status: 201, data: { ...location, ...data as object, id: '44444444-4444-4444-8444-444444444444', total_devices: 0, online_devices: 0 } }) as never);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Создать локацию' }));
  await within(dialog).findByText(/Сохранение подтверждено API/);
  expect(api.post).toHaveBeenCalledWith('/locations', expect.objectContaining({ name: 'New room', latitude: -90, longitude: 0, parent_location_id: id }));
});
it('delete requires explicit confirmation and an owned revision', async () => {
  render(<LocationsPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Удалить локацию Remote' }));
  const dialog = await screen.findByRole('dialog');
  const confirm = await within(dialog).findByRole('button', { name: 'Подтвердить удаление' });
  await waitFor(() => expect(confirm).toBeEnabled());
  expect(dialog.textContent).toContain('Дочерние локации станут корневыми');
  expect(api.delete).not.toHaveBeenCalled();
  jest.mocked(api.delete).mockResolvedValue({ status: 204 } as never);
  fireEvent.click(confirm);
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(api.delete).toHaveBeenCalledWith('/locations/' + id, { params: { expected_updated_at: original().updated_at } });
});
it('delete failure remains visible and never closes as success', async () => {
  render(<LocationsPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Удалить локацию Remote' }));
  const dialog = await screen.findByRole('dialog');
  const confirm = await within(dialog).findByRole('button', { name: 'Подтвердить удаление' });
  await waitFor(() => expect(confirm).toBeEnabled());
  jest.mocked(api.delete).mockRejectedValue({ response: { status: 409 } }); fireEvent.click(confirm);
  await within(dialog).findByText(/Конфликт:/); expect(confirm).toBeDisabled();
});
it('manager can edit geography but cannot delete a location', async () => {
  useAuthStore.setState({ user: { ...useAuthStore.getState().user!, role: 'device_manager' } });
  render(<LocationsPage />, { wrapper: createWrapper() });
  expect(await screen.findByRole('button', { name: 'Изменить локацию Remote' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Удалить локацию Remote' })).not.toBeInTheDocument();
});
it('dirty close asks for discard and can keep the draft', async () => {
  const { dialog } = await open();
  fireEvent.change(within(dialog).getByLabelText('Адрес'), { target: { value: 'Dirty' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Закрыть' }));
  await within(dialog).findByText('Отбросить несохранённый черновик?');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Оставить черновик' }));
  expect(within(dialog).getByLabelText('Адрес')).toHaveValue('Dirty'); expect(api.put).not.toHaveBeenCalled();
});
it('fresh reads do not replace a dirty draft or authorize stale save', async () => {
  const { dialog, qc } = await open();
  fireEvent.change(within(dialog).getByLabelText('Адрес'), { target: { value: 'Dirty' } });
  location = { ...location, address: 'Other operator', updated_at: '2026-10-03T00:02:00Z' };
  await act(async () => { await qc.refetchQueries({ queryKey: ['location-detail'] }); });
  await within(dialog).findByText(/Состояние изменилось на сервере/);
  expect(within(dialog).getByLabelText('Адрес')).toHaveValue('Dirty');
  expect(within(dialog).getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled();
});
it('pending write prevents a second request and modal closure', async () => {
  const { dialog } = await open();
  fireEvent.change(within(dialog).getByLabelText('Адрес'), { target: { value: 'Changed' } });
  let done!: (v: never) => void;
  jest.mocked(api.put).mockImplementation(() => new Promise(resolve => { done = resolve; }));
  const save = within(dialog).getByRole('button', { name: 'Сохранить изменения' });
  fireEvent.click(save); fireEvent.click(save);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Закрыть' }));
  expect(screen.getByRole('dialog')).toBeInTheDocument(); expect(api.put).toHaveBeenCalledTimes(1);
  await act(async () => { done({ status: 200, data: { ...location, address: 'Changed' } } as never); });
});
it('foreign catalog cannot expose or authorize the prior organization', async () => {
  jest.mocked(api.get).mockResolvedValue({ data: [{ ...location, org_id: childId }] } as never);
  render(<LocationsPage />, { wrapper: createWrapper() });
  await screen.findByText(/Не удалось получить достоверный каталог/);
  expect(screen.queryByText('Remote')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Создать локацию' })).toBeDisabled();
});
