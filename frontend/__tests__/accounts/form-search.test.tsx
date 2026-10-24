import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AccountsPage from '@/app/(dashboard)/accounts/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

const mockQuery = jest.fn();
const mockRefetch = jest.fn();
let mockReadError = false;
jest.mock('@/lib/hooks/useGameAccounts', () => ({
  ...jest.requireActual('@/lib/hooks/useGameAccounts'),
  useGameAccounts: (params: unknown) => {
    mockQuery(params);
    return { data: { items: [], total: 150, pages: 3 }, isLoading: false, isError: mockReadError, isFetching: false, refetch: mockRefetch };
  },
  useAccountStats: () => ({ data: undefined }),
  useServers: () => ({ data: { servers: [] } }),
}));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
jest.mock('@/components/sphere/DeviceSearchSelect', () => ({ DeviceSearchSelect: () => null }));

beforeEach(() => { jest.clearAllMocks(); mockReadError = false; jest.mocked(api.post).mockResolvedValue({ data: {} } as never); });

async function createDialog() {
  render(<AccountsPage />, { wrapper: createWrapper() });
  await userEvent.click(screen.getByRole('button', { name: 'Создать' }));
  fireEvent.change(screen.getByPlaceholderText('Ivan_Petrov'), { target: { value: 'Audit_User' } });
  fireEvent.change(screen.getByPlaceholderText('Авто-генерация если пусто'), { target: { value: 'test-only-password' } });
  return within(screen.getByRole('dialog')).getByRole('button', { name: 'Создать' });
}

it.each([0, 100, 65])('preserves lawfulness %s in the actual create POST', async (value) => {
  const submit = await createDialog();
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Законопослушность' }), { target: { value: String(value) } });
  await userEvent.click(submit);
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/game-accounts', expect.objectContaining({ lawfulness: value })));
});

it('omits an unset lawfulness rather than inventing the placeholder value', async () => {
  const submit = await createDialog();
  await userEvent.click(submit);
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(jest.mocked(api.post).mock.calls[0][1]).not.toHaveProperty('lawfulness');
});

it.each(['-1', '101', '3.5'])('blocks invalid lawfulness %s without sending a truncated number', async (value) => {
  const submit = await createDialog();
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Законопослушность' }), { target: { value } });
  expect(screen.getByRole('alert')).toHaveTextContent('Введите целое число от 0 до 100');
  expect(submit).toBeDisabled();
  fireEvent.click(submit);
  expect(api.post).not.toHaveBeenCalled();
});

it('applies only the final fast search after a full debounce delay and resets the page', () => {
  jest.useFakeTimers();
  try {
    const { unmount } = render(<AccountsPage />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByRole('button', { name: 'Следующая страница аккаунтов' }));
    expect(mockQuery).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
    const input = screen.getByPlaceholderText('Поиск по нику, логину...');
    fireEvent.change(input, { target: { value: 'a' } });
    act(() => { jest.advanceTimersByTime(100); });
    fireEvent.change(input, { target: { value: 'ab' } });
    act(() => { jest.advanceTimersByTime(100); });
    fireEvent.change(input, { target: { value: 'abc' } });
    act(() => { jest.advanceTimersByTime(299); });
    expect(mockQuery.mock.calls.some(([params]) => params.search)).toBe(false);
    act(() => { jest.advanceTimersByTime(1); });
    expect(mockQuery).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'abc', page: 1 }));
    expect(mockQuery.mock.calls.some(([params]) => params.search === 'a' || params.search === 'ab')).toBe(false);
    fireEvent.change(input, { target: { value: 'pending' } });
    const calls = mockQuery.mock.calls.length;
    unmount();
    act(() => { jest.advanceTimersByTime(300); });
    expect(mockQuery).toHaveBeenCalledTimes(calls);
  } finally { jest.useRealTimers(); }
});

it('distinguishes a catalog failure from an empty result and exposes recovery', () => {
  mockReadError = true;
  render(<AccountsPage />, { wrapper: createWrapper() });
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить аккаунты');
  expect(screen.queryByText('Нет аккаунтов. Создайте первый!')).not.toBeInTheDocument();
  expect(screen.getByText(/число записей не подтверждено/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку аккаунтов' }));
  expect(mockRefetch).toHaveBeenCalledTimes(1);
});
