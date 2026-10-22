import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { VpnProfileCatalog } from '@/src/features/vpn/VpnProfileCatalog';
import { VpnProfileInspector } from '@/src/features/vpn/VpnProfileInspector';
import { parseProfilePage } from '@/src/features/vpn/profileTypes';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
const get = jest.mocked(api.get); const post = jest.mocked(api.post);
const id = '018d83cc-1111-4444-8888-000000000001';
const revisionId = '018d83cc-1111-4444-8888-000000000002';
const requestId = '018d83cc-1111-4444-8888-000000000003';
const row = { id, revision_id: revisionId, name: 'Local egress', description: 'Test profile', provider_id: 'android-amneziawg' as const,
  protocol: 'amneziawg' as const, protocol_version: '3.1', current_revision: 1, is_archived: false,
  traffic_policy: { mode: 'selected_apps' as const, control_plane: 'bypass' as const, kill_switch: 'selected_apps' as const, ipv6: 'block' as const, included_packages: ['org.example.application'] } };
const page = { items: [row], total: 1, page: 1, page_size: 10 };
const saved = { profile_id: id, revision_id: revisionId, revision: 1, request_id: requestId, persisted: true, apply_allowed: false, execution_confirmed: false };

it('reads a wide scope without inventing an app count or accepting arbitrary exclusions', () => {
  const wide = { ...row, traffic_policy: { mode: 'all_apps_except_control', kill_switch: 'all_apps_except_control', control_plane: 'bypass', ipv6: 'block' } };
  expect(parseProfilePage({ ...page, items: [wide] }, 1).items[0].traffic_policy).toEqual(wide.traffic_policy);
  for (const extra of [{ included_packages: [] }, { excluded_uids: [1000] }, { kill_switch: 'selected_apps' }]) {
    expect(() => parseProfilePage({ ...page, items: [{ ...wide, traffic_policy: { ...wide.traffic_policy, ...extra } }] }, 1)).toThrow();
  }
});

beforeEach(() => {
  jest.resetAllMocks();
  useAuthStore.setState({ user: { id: 'actor', org_id: 'org', role: 'org_admin', email: 'test@example.org' }, sessionVersion: 1 });
  Object.defineProperty(globalThis.crypto, 'randomUUID', { configurable: true, value: () => requestId });
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
  get.mockResolvedValue({ data: page });
});

async function fill(user: ReturnType<typeof userEvent.setup>) {
  const file = new File(['private-sentinel'], 'test.conf', { type: 'text/plain' });
  Object.defineProperty(file, 'text', { value: () => Promise.resolve('private-sentinel') });
  await user.upload(screen.getByLabelText('Файл VPN-профиля'), file);
  await user.type(screen.getByLabelText('Название профиля'), 'Local egress');
  await user.type(screen.getByLabelText(/Приложения через VPN/), 'org.example.application');
}

it('renders only metadata and exposes no connection button', async () => {
  render(<VpnProfileCatalog canWrite />);
  expect(await screen.findByText('Local egress')).toBeInTheDocument();
  expect(screen.getByText(/Политика: Sphere вне VPN/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Подключить/ })).not.toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
  const parsed = parseProfilePage({ ...page, items: [{ ...row, config_text: 'private-sentinel' }] }, 1);
  expect(JSON.stringify(parsed)).not.toContain('private-sentinel');
});

it('imports once with a stable ID and clears the raw file', async () => {
  post.mockResolvedValue({ data: saved });
  const user = userEvent.setup(); const changed = jest.fn();
  render(<VpnProfileInspector purpose="save" onClose={jest.fn()} onSaved={changed} />);
  await fill(user);
  await user.click(screen.getByRole('button', { name: 'Проверить и сохранить' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Профиль сохранён · версия 1');
  expect(post).toHaveBeenCalledTimes(1);
  expect(post.mock.calls[0][0]).toBe('/vpn/profiles');
  expect(post.mock.calls[0][1]).toMatchObject({ request_id: requestId, name: 'Local egress' });
  expect(changed).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Проверить и сохранить' })).toBeDisabled();
  expect(document.body.textContent).not.toContain('private-sentinel');
});

it('keeps an unknown save frozen and resolves it with a read rather than a second import', async () => {
  post.mockRejectedValue(new Error('timeout'));
  get.mockResolvedValueOnce({ data: saved });
  const user = userEvent.setup();
  render(<VpnProfileInspector purpose="save" onClose={jest.fn()} />);
  await fill(user); await user.click(screen.getByRole('button', { name: 'Проверить и сохранить' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Результат сохранения неизвестен');
  expect(screen.getByRole('button', { name: 'Проверить и сохранить' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Проверить статус сохранения' }));
  expect(await screen.findByRole('status')).toHaveTextContent('VPN не подключался');
  expect(post).toHaveBeenCalledTimes(1);
  expect(get.mock.calls[0][0]).toBe(`/vpn/profiles/imports/${requestId}`);
});

it('never treats a not-yet-observed import as a cancelled write', async () => {
  post.mockRejectedValue(new Error('timeout')); get.mockRejectedValue({ response: { status: 404 } });
  const user = userEvent.setup();
  render(<VpnProfileInspector purpose="save" onClose={jest.fn()} />);
  await fill(user); await user.click(screen.getByRole('button', { name: 'Проверить и сохранить' }));
  await screen.findByRole('alert'); await user.click(screen.getByRole('button', { name: 'Проверить статус сохранения' }));
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('мог ещё выполняться'));
  expect(screen.getByRole('button', { name: 'Проверить и сохранить' })).toBeDisabled();
  expect(post).toHaveBeenCalledTimes(1);
});

it('sends the expected revision for an update and keeps the immutable history', async () => {
  post.mockResolvedValue({ data: { ...saved, revision: 2 } });
  const user = userEvent.setup();
  render(<VpnProfileInspector purpose="save" target={row} onClose={jest.fn()} />);
  const file = new File(['config'], 'test.conf', { type: 'text/plain' });
  Object.defineProperty(file, 'text', { value: () => Promise.resolve('config') });
  await user.upload(screen.getByLabelText('Файл VPN-профиля'), file);
  await user.click(screen.getByRole('button', { name: 'Проверить и сохранить' }));
  expect(await screen.findByRole('status')).toHaveTextContent('версия 2');
  expect(post.mock.calls[0][0]).toBe(`/vpn/profiles/${id}/revisions`);
  expect(post.mock.calls[0][1]).toMatchObject({ expected_revision: 1 });
});

it('shows a catalog error rather than a fabricated empty list and hides write controls for viewers', async () => {
  get.mockRejectedValue(new Error('unavailable'));
  render(<VpnProfileCatalog canWrite={false} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('недоступен');
  expect(screen.queryByRole('button', { name: 'Импорт профиля' })).not.toBeInTheDocument();
  expect(screen.queryByText(/Профилей пока нет/)).not.toBeInTheDocument();
});

it('requires explicit archive confirmation and checks the revision receipt', async () => {
  post.mockResolvedValue({ data: { ...row, is_archived: true, apply_allowed: false } });
  const user = userEvent.setup();
  render(<VpnProfileCatalog canWrite />);
  await screen.findByText('Local egress');
  await user.click(screen.getByRole('button', { name: 'Архивировать Local egress' }));
  expect(post).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'В архив' }));
  expect(await screen.findByText('Профиль перенесён в архив.')).toBeInTheDocument();
  expect(post.mock.calls[0][1]).toEqual({ expected_revision: 1 });
});
