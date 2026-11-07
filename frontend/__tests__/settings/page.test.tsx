import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SettingsPage from '@/app/(dashboard)/settings/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { toast } from 'sonner';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

const account = {
  id: 'user-1', org_id: 'org-1', email: 'operator@example.test', role: 'org_owner',
  is_active: true, mfa_enabled: false, created_at: '2026-01-01T10:00:00Z', last_login_at: null,
};
const key = {
  id: 'key-1', name: 'CI pipeline', key_prefix: 'sphr_test', permissions: [], is_active: true,
  expires_at: null, last_used_at: null, created_at: '2026-09-29T09:30:00Z',
};
const clients: QueryClient[] = [];

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><SettingsPage /></QueryClientProvider>);
  return client;
}
async function openTab(name: string) {
  await userEvent.click(screen.getByRole('tab', { name }));
}
beforeEach(() => {
  useAuthStore.setState({ user: account });
  jest.mocked(api.get).mockImplementation(async (url) => ({ data: url === '/auth/me' ? account : [] }) as never);
  jest.mocked(api.post).mockResolvedValue({ data: {} });
  jest.mocked(api.delete).mockResolvedValue({ data: null });
});
afterEach(() => { clients.splice(0).forEach((client) => client.clear()); jest.clearAllMocks(); });

it('uses the server profile without invented session dates or email verification', async () => {
  renderSettings();
  expect(await screen.findByText('Профиль из API')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/auth/me');
  expect(api.get).not.toHaveBeenCalledWith('/auth/api-keys');
  expect(screen.getByText('Аккаунт создан')).toBeInTheDocument();
  expect(screen.getByText('Последний вход')).toBeInTheDocument();
  expect(screen.queryByText('Сессия создана')).not.toBeInTheDocument();
  expect(screen.queryByText('Email верифицирован')).not.toBeInTheDocument();
});

it('reads enabled MFA from the API and confirms disable before sending one request', async () => {
  let enabled = true;
  jest.mocked(api.get).mockImplementation(async () => ({ data: { ...account, mfa_enabled: enabled } }) as never);
  jest.mocked(api.delete).mockImplementation(async () => { enabled = false; return { data: null } as never; });
  renderSettings();
  await screen.findByText('Включена');
  await openTab('Безопасность');
  expect(screen.queryByRole('button', { name: 'Настроить MFA' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Отключить MFA' }));
  expect(api.delete).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Отмена' }));
  expect(api.delete).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Отключить MFA' }));
  await userEvent.click(screen.getByRole('button', { name: 'Подтвердить отключение' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(api.delete).toHaveBeenCalledTimes(1);
  expect(api.delete).toHaveBeenCalledWith('/auth/mfa');
  expect(await screen.findByRole('button', { name: 'Настроить MFA' })).toBeEnabled();
});

it('keeps unknown MFA disabled when the profile cannot be fetched', async () => {
  jest.mocked(api.get).mockRejectedValue(new Error('network error'));
  renderSettings();
  expect(await screen.findByRole('alert')).toHaveTextContent('Статус защиты сейчас не подтверждён');
  await openTab('Безопасность');
  expect(screen.getByRole('button', { name: 'Настроить MFA' })).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});

it('distinguishes API-key failures from a successful empty list and supports explicit reload', async () => {
  let unavailable = true;
  jest.mocked(api.get).mockImplementation(async (url) => {
    if (url === '/auth/me') return { data: account } as never;
    if (unavailable) throw { response: { data: { detail: 'Permission denied' } } };
    return { data: [] } as never;
  });
  renderSettings();
  await openTab('API-ключи');
  expect(await screen.findByRole('alert')).toHaveTextContent('Permission denied');
  expect(screen.queryByText('Активных API-ключей нет')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Создать ключ' })).toBeDisabled();
  unavailable = false;
  await userEvent.click(screen.getByRole('button', { name: 'Обновить ключи' }));
  expect(await screen.findByText('Активных API-ключей нет')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Создать ключ' })).toBeEnabled();
});

it('rejects a malformed key-list response instead of rendering it as empty', async () => {
  jest.mocked(api.get).mockImplementation(async (url) => ({ data: url === '/auth/me' ? account : { items: [] } }) as never);
  renderSettings();
  await openTab('API-ключи');
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить API-ключи');
  expect(screen.queryByText('Активных API-ключей нет')).not.toBeInTheDocument();
});

it('preserves a previous key-list snapshot and blocks mutations after refresh failure', async () => {
  let failure = false;
  jest.mocked(api.get).mockImplementation(async (url) => {
    if (url === '/auth/me') return { data: account } as never;
    if (failure) throw new Error('unavailable');
    return { data: [key] } as never;
  });
  renderSettings();
  await openTab('API-ключи');
  expect(await screen.findByRole('article', { name: 'API-ключ CI pipeline' })).toBeInTheDocument();
  failure = true;
  await userEvent.click(screen.getByRole('button', { name: 'Обновить ключи' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Сохранён последний успешный список');
  expect(screen.getByRole('article')).toHaveTextContent('Список разрешений пуст');
  expect(screen.getByRole('button', { name: 'Отозвать ключ CI pipeline' })).toBeDisabled();
});

it('retains the revoke confirmation on failure and never retries the mutation automatically', async () => {
  jest.mocked(api.get).mockImplementation(async (url) => ({ data: url === '/auth/me' ? account : [key] }) as never);
  jest.mocked(api.delete).mockRejectedValue({ response: { data: { detail: 'Revoke rejected' } } });
  renderSettings();
  await openTab('API-ключи');
  await userEvent.click(await screen.findByRole('button', { name: 'Отозвать ключ CI pipeline' }));
  expect(api.delete).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Подтвердить отзыв' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Revoke rejected');
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(api.delete).toHaveBeenCalledTimes(1);
  expect(api.delete).toHaveBeenCalledWith('/auth/api-keys/key-1');
});

it('creates one key despite rapid submissions and hides its one-time value on close', async () => {
  let finish!: (value: { data: { name: string; raw_key: string } }) => void;
  jest.mocked(api.post).mockImplementation(() => new Promise((resolve) => { finish = resolve; }) as never);
  renderSettings();
  await openTab('API-ключи');
  await screen.findByText('Активных API-ключей нет');
  await userEvent.click(screen.getByRole('button', { name: 'Создать ключ' }));
  fireEvent.change(screen.getByLabelText('Название интеграции'), { target: { value: '  CI test  ' } });
  const form = screen.getByLabelText('Название интеграции').closest('form')!;
  fireEvent.submit(form); fireEvent.submit(form);
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(api.post).toHaveBeenCalledWith('/auth/api-keys', { name: 'CI test' });
  finish({ data: { name: 'CI test', raw_key: 'test-only-one-time-key' } });
  expect(await screen.findByText('test-only-one-time-key')).toBeInTheDocument();
  expect(within(screen.getByRole('dialog')).queryByRole('button', { name: 'Создать' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Закрыть и скрыть ключ' }));
  expect(screen.queryByText('test-only-one-time-key')).not.toBeInTheDocument();
});

it('does not claim successful clipboard copying after a rejected write', async () => {
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: jest.fn().mockRejectedValue(new Error('denied')) } });
  renderSettings();
  await screen.findByText('Профиль из API');
  fireEvent.click(screen.getByRole('button', { name: 'Скопировать Email' }));
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Не удалось скопировать')));
});

it('verifies a six-digit MFA code, clears the secret, and updates the server status', async () => {
  let enabled = false;
  jest.mocked(api.get).mockImplementation(async () => ({ data: { ...account, mfa_enabled: enabled } }) as never);
  jest.mocked(api.post).mockImplementation(async (url) => {
    if (url === '/auth/mfa/setup') return { data: { qr_code: 'test-png', secret: 'TESTSECRET' } } as never;
    enabled = true; return { data: { message: 'MFA enabled successfully' } } as never;
  });
  renderSettings();
  await screen.findByText('Профиль из API');
  await openTab('Безопасность');
  await userEvent.click(screen.getByRole('button', { name: 'Настроить MFA' }));
  expect(await screen.findByAltText('QR-код для настройки MFA')).toHaveAttribute('src', 'data:image/png;base64,test-png');
  expect(screen.queryByText('TESTSECRET')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('2. Код из аутентификатора'), { target: { value: '12xx3456' } });
  await userEvent.click(screen.getByRole('button', { name: 'Подтвердить MFA' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/auth/mfa/verify-setup', { code: '123456' }));
  expect(await screen.findByRole('button', { name: 'Отключить MFA' })).toBeEnabled();
  expect(screen.queryByAltText('QR-код для настройки MFA')).not.toBeInTheDocument();
});

it('retains the MFA setup on expiry failure and discards it when leaving Security', async () => {
  jest.mocked(api.post).mockImplementation(async (url) => {
    if (url === '/auth/mfa/setup') return { data: { qr_code: 'test-png', secret: 'TESTSECRET' } } as never;
    throw { response: { data: { detail: 'MFA setup session expired. Please restart setup.' } } };
  });
  renderSettings();
  await screen.findByText('Профиль из API');
  await openTab('Безопасность');
  await userEvent.click(screen.getByRole('button', { name: 'Настроить MFA' }));
  await screen.findByAltText('QR-код для настройки MFA');
  fireEvent.change(screen.getByLabelText('2. Код из аутентификатора'), { target: { value: '123456' } });
  await userEvent.click(screen.getByRole('button', { name: 'Подтвердить MFA' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('session expired');
  expect(screen.getByLabelText('2. Код из аутентификатора')).toHaveValue('123456');
  expect(api.post).toHaveBeenCalledTimes(2);
  await openTab('Профиль');
  await openTab('Безопасность');
  expect(screen.queryByAltText('QR-код для настройки MFA')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Настроить MFA' })).toBeEnabled();
});

it('retains the create form when no usable one-time key receipt is returned', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { name: 'CI test' } });
  renderSettings();
  await openTab('API-ключи');
  await screen.findByText('Активных API-ключей нет');
  await userEvent.click(screen.getByRole('button', { name: 'Создать ключ' }));
  fireEvent.change(screen.getByLabelText('Название интеграции'), { target: { value: 'CI test' } });
  await userEvent.click(screen.getByRole('button', { name: /^Создать$/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Проверьте список ключей перед повторным запросом');
  expect(screen.getByLabelText('Название интеграции')).toHaveValue('CI test');
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('Ключ создан')).not.toBeInTheDocument();
});
