import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TextEncoder } from 'util';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { VpnProfileBatchImport } from '@/src/features/vpn/VpnProfileBatchImport';
import { parseBatchCheck, parseBatchSaved, parseBatchStatus } from '@/src/features/vpn/profileBatchTypes';

jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
const post = jest.mocked(api.post);
const config = '[Interface]\nPrivateKey = private-sentinel\nAddress = 10.0.0.2/32\n[Peer]\nAllowedIPs = 0.0.0.0/0';
const uuid = (n: number) => `018d83cc-1111-4444-8888-${String(n).padStart(12, '0')}`;
const items = [1, 2].map(n => ({ request_id: uuid(n), name: `Exit ${n}` }));
const check = { items: items.map(v => ({ request_id: v.request_id, config_valid: true, issues: [] })), config_valid: true, persisted: false, apply_allowed: false, execution_confirmed: false };
const receipts = items.map((v, i) => ({ request_id: v.request_id, profile_id: uuid(i + 10), revision_id: uuid(i + 20), revision: 1, persisted: true, apply_allowed: false, execution_confirmed: false }));
const saved = { items: receipts, persisted: true, apply_allowed: false, execution_confirmed: false };

beforeEach(() => {
  jest.resetAllMocks(); let n = 0;
  Object.defineProperty(globalThis.crypto, 'randomUUID', { configurable: true, value: () => uuid(++n) });
  Object.defineProperty(globalThis, 'TextEncoder', { configurable: true, value: TextEncoder });
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
  useAuthStore.setState({ user: { id: 'actor', org_id: 'org', role: 'org_admin', email: 'test@example.org' }, sessionVersion: 1 });
});

function file(name = 'Exit 1.conf') {
  const f = new File([config], name, { type: 'text/plain' });
  Object.defineProperty(f, 'text', { value: () => Promise.resolve(config) });
  return f;
}

async function load(user: ReturnType<typeof userEvent.setup>) {
  await user.upload(screen.getByLabelText('Файлы VPN-профилей'), [file(), file('Exit 2.conf')]);
  await user.type(screen.getByLabelText(/Приложения через VPN/), 'org.example.application');
  expect(screen.getByText('Выбрано 2')).toBeInTheDocument();
}

it('checks each file then saves once with stable per-item IDs and no secret in the DOM', async () => {
  post.mockResolvedValueOnce({ data: check }).mockResolvedValueOnce({ data: saved });
  const user = userEvent.setup(); const changed = jest.fn();
  render(<VpnProfileBatchImport onClose={jest.fn()} onSaved={changed} />);
  expect(screen.getByRole('dialog', { name: 'Массовый импорт профилей' })).toBeInTheDocument();
  await load(user);
  expect(screen.getByRole('button', { name: 'Сохранить 2 профилей' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Проверить пакет' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить 2 профилей' })).toBeEnabled());
  await user.click(screen.getByRole('button', { name: 'Сохранить 2 профилей' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Сохранено профилей: 2');
  expect(post.mock.calls.map(c => c[0])).toEqual(['/vpn/profiles/batch/preflight', '/vpn/profiles/batch']);
  expect(post.mock.calls[0][1]).toEqual(post.mock.calls[1][1]);
  expect(changed).toHaveBeenCalledTimes(1);
  expect(document.body.textContent).not.toContain('private-sentinel');
  expect(screen.getByLabelText('Файлы VPN-профилей')).toBeDisabled();
});

it('recovers an unknown result through status only, and does not equate null to cancelled', async () => {
  post.mockResolvedValueOnce({ data: check }).mockRejectedValueOnce(new Error('timeout'))
    .mockResolvedValueOnce({ data: { items: items.map(v => ({ request_id: v.request_id, receipt: null })) } })
    .mockResolvedValueOnce({ data: { items: items.map((v, i) => ({ request_id: v.request_id, receipt: receipts[i] })) } });
  const user = userEvent.setup(); render(<VpnProfileBatchImport onClose={jest.fn()} onSaved={jest.fn()} />);
  await load(user); await user.click(screen.getByRole('button', { name: 'Проверить пакет' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить 2 профилей' })).toBeEnabled());
  await user.click(screen.getByRole('button', { name: 'Сохранить 2 профилей' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Результат сохранения неизвестен');
  await user.click(screen.getByRole('button', { name: 'Проверить статус пакета' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('это не отмена запроса');
  await user.click(screen.getByRole('button', { name: 'Проверить статус пакета' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Сохранено профилей: 2');
  expect(post.mock.calls.map(c => c[0]).filter(p => p === '/vpn/profiles/batch')).toHaveLength(1);
  expect(post.mock.calls[2][1]).toEqual({ request_ids: items.map(v => v.request_id) });
});

it('invalidates the check after changing the common app policy', async () => {
  post.mockResolvedValueOnce({ data: check });
  const user = userEvent.setup(); render(<VpnProfileBatchImport onClose={jest.fn()} onSaved={jest.fn()} />);
  await load(user); await user.click(screen.getByRole('button', { name: 'Проверить пакет' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Сохранить 2 профилей' })).toBeEnabled());
  await user.click(screen.getByRole('button', { name: 'Параметры пакета' }));
  await user.type(screen.getByLabelText(/Приложения через VPN/), '\norg.example.second');
  expect(screen.getByRole('button', { name: 'Сохранить 2 профилей' })).toBeDisabled();
});

it('rejects over 100 files before reading or sending secrets', async () => {
  render(<VpnProfileBatchImport onClose={jest.fn()} onSaved={jest.fn()} />);
  fireEvent.change(screen.getByLabelText('Файлы VPN-профилей'), { target: { files: Array.from({ length: 101 }, () => file()) } });
  expect(await screen.findByRole('alert')).toHaveTextContent('до 100 файлов');
  expect(post).not.toHaveBeenCalled();
});

it('brings failed files forward and allows returning to the whole package', async () => {
  post.mockResolvedValueOnce({ data: { ...check, config_valid: false, items: [check.items[0],
    { request_id: items[1].request_id, config_valid: false, issues: [{ code: 'invalid_field_value', line: 8 }] }] } });
  const user = userEvent.setup(); render(<VpnProfileBatchImport onClose={jest.fn()} onSaved={jest.fn()} />);
  await load(user); await user.click(screen.getByRole('button', { name: 'Проверить пакет' }));
  expect(await screen.findByText('Конфигурация не прошла проверку · строка 8')).toBeInTheDocument();
  expect(screen.queryByText('Exit 1')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Сохранить 2 профилей' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Все профили' }));
  expect(screen.getByText('Exit 1')).toBeInTheDocument();
});

it('discards a response after account/session change', async () => {
  let resolve: (value: unknown) => void = () => {};
  post.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  const user = userEvent.setup(); const close = jest.fn();
  render(<VpnProfileBatchImport onClose={close} onSaved={jest.fn()} />);
  await load(user); await user.click(screen.getByRole('button', { name: 'Проверить пакет' }));
  act(() => useAuthStore.setState({ sessionVersion: 2 }));
  await act(async () => { resolve({ data: check }); });
  expect(close).toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Сохранить 2 профилей' })).toBeDisabled();
});

it('rejects mismatched item IDs, false aggregate verdicts and foreign save receipts', () => {
  expect(parseBatchCheck(check, items)).toHaveLength(2);
  expect(() => parseBatchCheck({ ...check, config_valid: false }, items)).toThrow();
  expect(() => parseBatchCheck({ ...check, items: [...check.items].reverse() }, items)).toThrow();
  expect(() => parseBatchSaved({ ...saved, items: [...receipts].reverse() }, items)).toThrow();
  expect(() => parseBatchStatus({ items: [{ request_id: uuid(500), receipt: null }, { request_id: uuid(2), receipt: null }] }, items)).toThrow();
  expect(parseBatchStatus({ items: items.map(v => ({ request_id: v.request_id, receipt: null })) }, items)).toEqual([null, null]);
});
