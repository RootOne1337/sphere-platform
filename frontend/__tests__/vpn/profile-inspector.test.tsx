import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { validProfileReceipt, VpnProfileInspector } from '@/src/features/vpn/VpnProfileInspector';

jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
const post = jest.mocked(api.post);
const receipt = { schema_version: 1, config_valid: true, apply_allowed: false, persisted: false,
  execution_confirmed: false, issues: [], blockers: ['android_provider_not_integrated'] };

beforeEach(() => {
  jest.clearAllMocks();
  useAuthStore.setState({ user: { id: 'admin', org_id: 'org', email: 'admin@example.org', role: 'org_admin' }, sessionVersion: 1 });
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
});

async function load(user: ReturnType<typeof userEvent.setup>, text = '[Interface]\nPrivateKey = private-sentinel') {
  const file = new File([text], 'example.conf', { type: 'text/plain' });
  Object.defineProperty(file, 'text', { value: jest.fn().mockResolvedValue(text) });
  await user.upload(screen.getByLabelText('Файл VPN-профиля'), file);
  await user.type(screen.getByLabelText(/Приложения через VPN/), 'org.example.application');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Проверить профиль' })).toBeEnabled());
}

it('inspects without an apply action and releases the imported config after submission', async () => {
  post.mockResolvedValue({ data: receipt });
  const user = userEvent.setup();
  render(<VpnProfileInspector onClose={jest.fn()} />);
  await load(user);
  await user.click(screen.getByRole('button', { name: 'Проверить профиль' }));
  expect(await screen.findByText(/Формат профиля прошёл проверку/)).toBeInTheDocument();
  expect(screen.getByText(/Подключение пока недоступно/)).toBeInTheDocument();
  expect(post).toHaveBeenCalledTimes(1);
  expect(post.mock.calls[0][0]).toBe('/vpn/profile-preflight');
  expect(post.mock.calls[0][1]).toMatchObject({ protocol: 'amneziawg', protocol_version: '3.1',
    traffic_policy: { included_packages: ['org.example.application'], control_plane: 'bypass', kill_switch: 'selected_apps' } });
  expect(screen.getByRole('button', { name: 'Проверить профиль' })).toBeDisabled();
  expect((screen.getByLabelText('Файл VPN-профиля') as HTMLInputElement).value).toBe('');
  expect(document.body.textContent).not.toContain('private-sentinel');
  expect(screen.queryByRole('button', { name: /^Подключить/ })).not.toBeInTheDocument();
});

it('rejects oversized files before sending any request', async () => {
  const user = userEvent.setup();
  render(<VpnProfileInspector onClose={jest.fn()} />);
  await user.upload(screen.getByLabelText('Файл VPN-профиля'), new File(['x'.repeat(65537)], 'large.conf', { type: 'text/plain' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('до 64 КиБ');
  expect(post).not.toHaveBeenCalled();
});

it('aborts a pending request on unmount and never exposes API error bodies', async () => {
  post.mockImplementation(() => new Promise(() => {}));
  const user = userEvent.setup();
  const view = render(<VpnProfileInspector onClose={jest.fn()} />);
  await load(user);
  await user.click(screen.getByRole('button', { name: 'Проверить профиль' }));
  const signal = post.mock.calls[0][2]?.signal;
  view.unmount();
  expect(signal?.aborted).toBe(true);
  expect(post).toHaveBeenCalledTimes(1);
});

it('clears an old result when policy changes and rejects a malformed success receipt', async () => {
  post.mockResolvedValueOnce({ data: receipt }).mockResolvedValueOnce({ data: { ...receipt, apply_allowed: true } });
  const user = userEvent.setup();
  render(<VpnProfileInspector onClose={jest.fn()} />);
  await load(user);
  await user.click(screen.getByRole('button', { name: 'Проверить профиль' }));
  await screen.findByRole('status');
  fireEvent.change(screen.getByLabelText('Версия конфигурации AWG'), { target: { value: '2' } });
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  await load(user);
  await user.click(screen.getByRole('button', { name: 'Проверить профиль' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Проверка не выполнена');
});

it('keeps validation errors generic even if the transport error contains a key', async () => {
  post.mockRejectedValue({ response: { data: { detail: 'private-sentinel' } }, config: { data: 'private-sentinel' } });
  const user = userEvent.setup();
  render(<VpnProfileInspector onClose={jest.fn()} />);
  await load(user);
  await user.click(screen.getByRole('button', { name: 'Проверить профиль' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Проверка не выполнена');
  expect(document.body.textContent).not.toContain('private-sentinel');
  expect(post).toHaveBeenCalledTimes(1);
});

it('aborts on session change and ignores a late response', async () => {
  let resolve: (value: unknown) => void = () => {};
  post.mockImplementation(() => new Promise(done => { resolve = done; }));
  const user = userEvent.setup();
  const close = jest.fn();
  render(<VpnProfileInspector onClose={close} />);
  await load(user);
  await user.click(screen.getByRole('button', { name: 'Проверить профиль' }));
  const signal = post.mock.calls[0][2]?.signal;
  act(() => useAuthStore.setState({ sessionVersion: 2 }));
  await waitFor(() => expect(close).toHaveBeenCalled());
  expect(signal?.aborted).toBe(true);
  await act(async () => { resolve({ data: receipt }); });
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it.each([null, {}, { ...receipt, persisted: true }, { ...receipt, execution_confirmed: true },
  { ...receipt, issues: [{ code: 'bad', line: 1 }] }, { ...receipt, blockers: [] }])('rejects a contradictory receipt: %p', value => {
  expect(validProfileReceipt(value)).toBe(false);
});
