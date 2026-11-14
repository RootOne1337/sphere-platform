import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CapabilitiesProvider, PermissionNotice, RouteAccessBoundary, useCapabilities } from '@/src/features/access/Capabilities';
import { canAccessRoute } from '@/src/features/access/routeAccess';
import { useAuthStore } from '@/lib/store';
import { api } from '@/lib/api';
import { useInspectorStore } from '@/src/features/inspector/inspectorStore';
import { useCommandPaletteStore } from '@/src/features/navigation/commandPaletteStore';
import rolePermissions from '../fixtures/session-capabilities.json';
import { SPHERE_NAV_GROUPS } from '@/src/features/navigation/navigationCatalog';
import { useEffect, useState } from 'react';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
const user = { id: 'u-1', org_id: 'org-1', role: 'viewer', email: 'viewer@example.org' };
const grants = ['device:read', 'stream:read', 'monitoring:read', 'script:read'];
function response(permissions = grants, fields = {}) {
  return { data: { schema_version: 1, user_id: user.id, org_id: user.org_id, role: user.role, permissions, ...fields } };
}
function Child() {
  const access = useCapabilities();
  return <><p>Private child</p><button disabled={!access.can('stream:control')}>Control</button></>;
}
function fixture(path = '/devices') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const tree = () => <QueryClientProvider client={client}><CapabilitiesProvider><RouteAccessBoundary pathname={path}><Child /></RouteAccessBoundary></CapabilitiesProvider></QueryClientProvider>;
  return { ...render(tree()), client, tree };
}
beforeEach(() => {
  get.mockReset();
  useAuthStore.setState({ user, accessToken: 'fixture', sessionVersion: 1 });
});
afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks(); });

it('keeps the private subtree unmounted until server permissions arrive', async () => {
  let resolve!: (v: unknown) => void;
  get.mockImplementationOnce(() => new Promise(r => { resolve = r; }) as never);
  fixture();
  expect(screen.getByRole('status')).toHaveTextContent('Проверяем доступ');
  expect(screen.queryByText('Private child')).not.toBeInTheDocument();
  await act(async () => resolve(response()));
  expect(await screen.findByText('Private child')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Control' })).toBeDisabled();
});

it.each(['/users', '/audit', '/discovery', '/scripts/builder', '/scripts/builder/script-1?from=devices', '/unknown'])('rejects direct link %s before its feature mounts', async path => {
  get.mockResolvedValue(response());
  fixture(path);
  expect(await screen.findByRole('alert')).toHaveTextContent('Раздел недоступен для вашей роли');
  expect(screen.queryByText('Private child')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Мой профиль' })).toHaveAttribute('href', '/settings');
});

it.each([403, 500])('explains a %s capability failure and retries without inventing access', async status => {
  get.mockRejectedValueOnce({ response: { status } }).mockResolvedValueOnce(response());
  fixture();
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось проверить права');
  expect(screen.queryByText('Private child')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить доступ снова' }));
  expect(await screen.findByText('Private child')).toBeInTheDocument();
});

it.each([{ user_id: 'other' }, { org_id: 'other' }, { schema_version: 2 }, { permissions: 'device:read' }])('rejects wrong ownership or malformed response %j', async fields => {
  get.mockResolvedValue(response(grants, fields));
  fixture();
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось проверить права');
  expect(screen.queryByText('Private child')).not.toBeInTheDocument();
});

it('does not reuse a prior identity response while the next identity is pending', async () => {
  get.mockResolvedValueOnce(response());
  const view = fixture();
  await screen.findByText('Private child');
  let resolve!: (v: unknown) => void;
  get.mockImplementationOnce(() => new Promise(r => { resolve = r; }) as never);
  act(() => useAuthStore.setState({ user: { ...user, id: 'u-2' }, sessionVersion: 2 }));
  expect(screen.queryByText('Private child')).not.toBeInTheDocument();
  await act(async () => resolve(response()));
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось проверить права');
  expect(view.client.getQueryData(['capabilities', 1, 'org-1', 'u-1', 'viewer'])).toBeUndefined();
});

it('withdraws controls immediately when a refreshed server role revokes permission', async () => {
  useAuthStore.setState({ user: { ...user, role: 'device_manager' } });
  get.mockResolvedValueOnce(response([...grants, 'stream:control'], { role: 'device_manager' }))
    .mockResolvedValue(response());
  const view = fixture();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Control' })).toBeEnabled());
  await act(async () => { await view.client.invalidateQueries({ queryKey: ['capabilities'] }); });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Control' })).toBeDisabled());
  expect(useAuthStore.getState().user?.role).toBe('viewer');
});

it('clears persistent inspector and palette state when the private session retires', async () => {
  get.mockResolvedValue(response());
  const view = fixture();
  await screen.findByText('Private child');
  act(() => { useInspectorStore.getState().openInspector('device', 'former-device'); useCommandPaletteStore.getState().open(); });
  view.unmount();
  expect(useInspectorStore.getState().isOpen).toBe(false);
  expect(useCommandPaletteStore.getState().isOpen).toBe(false);
});

it('does not use cached grants after a failed refresh', async () => {
  get.mockResolvedValueOnce(response()).mockRejectedValueOnce(new Error('offline'));
  const view = fixture();
  await screen.findByText('Private child');
  await act(async () => { await view.client.invalidateQueries({ queryKey: ['capabilities'] }); });
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось проверить права');
  expect(screen.queryByText('Private child')).not.toBeInTheDocument();
});

it('expires grants when a suspended tab has not received a fresh response', async () => {
  get.mockResolvedValueOnce(response());
  const view = fixture();
  await screen.findByText('Private child');
  jest.spyOn(Date, 'now').mockReturnValue(Date.now() + 95_000);
  view.rerender(view.tree());
  expect(screen.queryByText('Private child')).not.toBeInTheDocument();
});

it('never infers role hierarchy and checks the most specific route', () => {
  expect(canAccessRoute('/scripts/abc', ['script:read'], true)).toBe(true);
  expect(canAccessRoute('/scripts/builder/abc', ['script:read'], true)).toBe(false);
  expect(canAccessRoute('/users-old', ['user:read'], true)).toBe(false);
  expect(canAccessRoute('/settings', [], true)).toBe(true);
  expect(canAccessRoute('/settings', [], false)).toBe(false);
  expect(canAccessRoute('/webhooks', [], true)).toBe(true);
});

it('explains pending, denied and failed permission checks without reporting a server mutation', async () => {
  let resolve!: (v: unknown) => void;
  get.mockImplementationOnce(() => new Promise(r => { resolve = r; }) as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><CapabilitiesProvider><PermissionNotice permission="device:delete" action="удаление устройств" /></CapabilitiesProvider></QueryClientProvider>);
  expect(screen.getByRole('status')).toHaveTextContent('Проверяем права');
  await act(async () => resolve(response()));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Текущие права не разрешают удаление устройств'));
  get.mockRejectedValueOnce(new Error('offline'));
  await act(async () => { await client.invalidateQueries({ queryKey: ['capabilities'] }); });
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Не удалось подтвердить права'));
  expect(get.mock.calls.every(([path]) => path === '/auth/capabilities')).toBe(true);
});

it('removes the permission notice only after a verified grant arrives', async () => {
  get.mockResolvedValue(response([...grants, 'device:write']));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><CapabilitiesProvider><PermissionNotice permission="device:write" action="изменение устройства" /></CapabilitiesProvider></QueryClientProvider>);
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
});

it.each(Object.keys(rolePermissions) as Array<keyof typeof rolePermissions>)('offers the correct route and action set for server role %s', role => {
  const permissions = rolePermissions[role];
  const can = (path: string) => canAccessRoute(path, permissions, true);
  const administrative = ['org_admin', 'org_owner', 'super_admin'].includes(role);
  const manager = administrative || role === 'device_manager';
  expect(can('/users')).toBe(administrative);
  expect(can('/audit')).toBe(administrative);
  expect(can('/discovery')).toBe(manager);
  expect(can('/scripts/builder')).toBe(manager);
  expect(can('/vpn')).toBe(role !== 'script_runner' && role !== 'api_user');
  const links = SPHERE_NAV_GROUPS.flatMap(g => g.items).filter(i => can(i.href));
  expect(links.length).toBe(role === 'api_user' ? 2 : role === 'script_runner' ? 18 : role === 'viewer' ? 19 : role === 'device_manager' ? 20 : 22);
});

function studioFixture() {
  const mounted = jest.fn(), retired = jest.fn();
  function Editor() {
    const access = useCapabilities();
    const [draft, setDraft] = useState('');
    useEffect(() => { mounted(); return retired; }, []);
    return <div data-testid="retained-studio"><input aria-label="Private draft" value={draft} onChange={event => setDraft(event.target.value)} /><button disabled={!access.can('script:execute')}>Run retained</button></div>;
  }
  useAuthStore.setState({ user: { ...user, role: 'device_manager' } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const tree = () => <QueryClientProvider client={client}><CapabilitiesProvider><RouteAccessBoundary pathname="/scripts/builder"><Editor /></RouteAccessBoundary></CapabilitiesProvider></QueryClientProvider>;
  return { ...render(tree()), client, tree, mounted, retired };
}
const studioResponse = () => response([...grants, 'script:write', 'script:execute'], { role: 'device_manager' });

it('retains an already verified Studio hidden and inert through a transient capability failure, with no cached grants', async () => {
  get.mockResolvedValueOnce(studioResponse()).mockRejectedValueOnce({ response: { status: 503 } }).mockResolvedValueOnce(studioResponse());
  const view = studioFixture();
  fireEvent.change(await screen.findByLabelText('Private draft'), { target: { value: 'Unpublished and unknown launch state' } });
  await act(async () => { await view.client.invalidateQueries({ queryKey: ['capabilities'] }); });
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось проверить права');
  const editor = screen.getByTestId('retained-studio');
  expect(editor).not.toBeVisible(); expect(editor.parentElement).toHaveAttribute('inert');
  expect(screen.getByText('Run retained')).toBeDisabled();
  expect(view.retired).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить доступ снова' }));
  await waitFor(() => expect(screen.getByLabelText('Private draft')).toBeVisible());
  expect(screen.getByLabelText('Private draft')).toHaveValue('Unpublished and unknown launch state');
  expect(view.mounted).toHaveBeenCalledTimes(1);
});

it.each([400, 401, 403, 404])('retires retained Studio after an authoritative %s capability refusal', async status => {
  get.mockResolvedValueOnce(studioResponse()).mockRejectedValueOnce({ response: { status } });
  const view = studioFixture(); await screen.findByLabelText('Private draft');
  await act(async () => { await view.client.invalidateQueries({ queryKey: ['capabilities'] }); });
  await waitFor(() => expect(screen.queryByTestId('retained-studio')).not.toBeInTheDocument());
  expect(view.retired).toHaveBeenCalledTimes(1);
});

it('never retains Studio across a principal/session boundary or an unverified initial response', async () => {
  get.mockResolvedValueOnce(studioResponse());
  const view = studioFixture(); await screen.findByLabelText('Private draft');
  fireEvent.change(screen.getByLabelText('Private draft'), { target: { value: 'former private draft' } });
  let resolve!: (value: unknown) => void;
  get.mockImplementationOnce(() => new Promise(done => { resolve = done; }) as never);
  act(() => useAuthStore.setState({ user: { ...user, id: 'new-user', role: 'device_manager' }, sessionVersion: 2 }));
  expect(screen.queryByTestId('retained-studio')).not.toBeInTheDocument();
  await act(async () => resolve(studioResponse()));
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось проверить права');
  expect(screen.queryByTestId('retained-studio')).not.toBeInTheDocument();
});

it('retires Studio on revoked grants or malformed ownership instead of treating it as a network outage', async () => {
  get.mockResolvedValueOnce(studioResponse()).mockResolvedValueOnce(response(grants, { role: 'device_manager' }));
  const view = studioFixture(); await screen.findByLabelText('Private draft');
  await act(async () => { await view.client.invalidateQueries({ queryKey: ['capabilities'] }); });
  await waitFor(() => expect(screen.queryByTestId('retained-studio')).not.toBeInTheDocument());
  expect(view.retired).toHaveBeenCalledTimes(1);
  get.mockResolvedValueOnce(studioResponse());
  await act(async () => { await view.client.invalidateQueries({ queryKey: ['capabilities'] }); });
  await screen.findByLabelText('Private draft');
  get.mockResolvedValueOnce(response(grants, { org_id: 'wrong', role: 'device_manager' }));
  await act(async () => { await view.client.invalidateQueries({ queryKey: ['capabilities'] }); });
  await waitFor(() => expect(screen.queryByTestId('retained-studio')).not.toBeInTheDocument());
});
