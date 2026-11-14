import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, useQuery, useQueryClient } from '@tanstack/react-query';
import { Providers } from '@/app/providers';
import { useAuthStore } from '@/lib/store';
import { api } from '@/lib/api';
import { clearReturnDestination, normalizeReturnDestination, readReturnDestination, rememberReturnDestination } from '@/src/features/access/returnDestination';

let mockReady = true;
let mockPath = '/accounts';
const mockReplace = jest.fn();
const mockRetry = jest.fn();
let mockUnavailable = false;
jest.mock('next/navigation', () => ({
  usePathname: () => mockPath,
  useRouter: () => ({ replace: mockReplace }),
}));
jest.mock('@/lib/store', () => ({
  ...jest.requireActual('@/lib/store'),
  useInitAuth: () => ({ state: mockUnavailable ? 'unavailable' : mockReady ? 'ready' : 'checking', retry: mockRetry }),
}));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));

function identify(org: string) {
  useAuthStore.getState().setAccessToken(`access-${org}`);
  useAuthStore.getState().setUser({ id: `user-${org}`, org_id: org, email: 'audit@example.test', role: 'admin' });
}

beforeEach(() => {
  useAuthStore.getState().logout();
  localStorage.clear();
  mockReady = true;
  mockUnavailable = false;
  mockPath = '/accounts';
  window.history.replaceState({}, '', '/accounts');
  mockReplace.mockClear();
  mockRetry.mockClear();
  clearReturnDestination();
  jest.mocked(api.get).mockReset();
});

it('does not mount private children during refresh', () => {
  mockReady = false;
  const mounted = jest.fn();
  function Private() { mounted(); return <div>private accounts</div>; }
  render(<Providers><Private /></Providers>);
  expect(mounted).not.toHaveBeenCalled();
  expect(screen.queryByText('private accounts')).not.toBeInTheDocument();
});

it('blocks signed-out children before the login redirect completes', () => {
  render(<Providers><div>private accounts</div></Providers>);
  expect(screen.queryByText('private accounts')).not.toBeInTheDocument();
  expect(mockReplace).toHaveBeenCalledWith('/login');
});

it('allows the login route but does not treat a login prefix as public', () => {
  mockPath = '/login';
  const view = render(<Providers><div>login form</div></Providers>);
  expect(screen.getByText('login form')).toBeInTheDocument();
  mockPath = '/login-private';
  view.rerender(<Providers><div>private accounts</div></Providers>);
  expect(screen.queryByText('private accounts')).not.toBeInTheDocument();
  expect(mockReplace).toHaveBeenCalledWith('/login');
});

it('shows private content for an authenticated identity and unmounts it on logout', () => {
  identify('a');
  render(<Providers><div>private accounts</div></Providers>);
  expect(screen.getByText('private accounts')).toBeInTheDocument();
  act(() => useAuthStore.getState().logout());
  expect(screen.queryByText('private accounts')).not.toBeInTheDocument();
});

function capabilities(permissions: string[]) {
  jest.mocked(api.get).mockResolvedValue({ data: { schema_version: 1, user_id: 'user-a', org_id: 'a', role: 'admin', permissions } });
}

it('redirects an authenticated login visit after checking capability without mounting the form', async () => {
  identify('a');
  capabilities(['monitoring:read']);
  mockPath = '/login';
  render(<Providers><div>login form</div></Providers>);
  expect(screen.queryByText('login form')).not.toBeInTheDocument();
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/dashboard'));
});

it('returns to the authorized saved task after capability verification', async () => {
  identify('a');
  capabilities(['script:read']);
  rememberReturnDestination('/tasks/fixture-task?tab=logs');
  mockPath = '/login';
  render(<Providers><div>login form</div></Providers>);
  expect(mockReplace).not.toHaveBeenCalled();
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/tasks/fixture-task?tab=logs'));
});

it('captures recognized route context before login, without carrying unrelated query fields', () => {
  mockPath = '/logs';
  window.history.replaceState({}, '', '/logs?device_id=fixture-device&date=2026-11-13&unused=discard');
  render(<Providers><div>private logs</div></Providers>);
  expect(mockReplace).toHaveBeenCalledWith('/login');
  expect(readReturnDestination()).toBe('/logs?device_id=fixture-device&date=2026-11-13');
});

it('normalizes bounded context for known application routes', () => {
  expect(normalizeReturnDestination('/audit?request_id=audit-1&extra=skip')).toBe('/audit?request_id=audit-1');
  expect(normalizeReturnDestination('/orchestration?run_id=run-1&batch_id=batch-1')).toBe('/orchestration?run_id=run-1&batch_id=batch-1');
  expect(normalizeReturnDestination('/devices?location_id=site-1&unused=discard')).toBe('/devices?location_id=site-1');
  expect(normalizeReturnDestination('/tasks?device_id=device-1&script_id=script-1')).toBe('/tasks?device_id=device-1&script_id=script-1');
  expect(normalizeReturnDestination('/devices?location_id=site-1&location_id=site-2')).toBe('/devices');
  expect(normalizeReturnDestination('/stream/fixture?teach=1&teach=1')).toBe('/stream/fixture');
  expect(normalizeReturnDestination('/devices/fixture/unused')).toBeNull();
});

it('does not carry a route through an explicit logout', () => {
  identify('a');
  const view = render(<Providers><div>private accounts</div></Providers>);
  act(() => useAuthStore.getState().logout(true));
  view.rerender(<Providers><div>private accounts</div></Providers>);
  expect(readReturnDestination()).toBeNull();
  expect(mockReplace).toHaveBeenCalledWith('/login');
});

it('explains an inaccessible return target and offers a page available without monitoring permission', async () => {
  identify('a');
  capabilities([]);
  rememberReturnDestination('/audit?request_id=fixture-id');
  mockPath = '/login';
  render(<Providers><div>login form</div></Providers>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Запрошенный раздел недоступен');
  expect(mockReplace).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Открыть доступный раздел' }));
  expect(mockReplace).toHaveBeenCalledWith('/settings');
});

it('keeps the protected page unmounted when startup refresh is temporarily unavailable', () => {
  mockUnavailable = true;
  render(<Providers><div>private accounts</div></Providers>);
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось проверить сессию');
  expect(screen.queryByText('private accounts')).not.toBeInTheDocument();
  expect(mockReplace).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить проверку' }));
  expect(mockRetry).toHaveBeenCalledTimes(1);
});

it('isolates cached tenant data before rendering the next identity', async () => {
  identify('a');
  let currentClient: QueryClient;
  const fetchAccounts = jest.fn(async () => 'tenant A private credential');
  function Accounts() {
    currentClient = useQueryClient();
    const { data } = useQuery({ queryKey: ['accounts'], queryFn: fetchAccounts, staleTime: Infinity });
    return <div>{data ?? 'loading accounts'}</div>;
  }
  render(<Providers><Accounts /></Providers>);
  await screen.findByText('tenant A private credential');
  const retired = currentClient!;
  // Keep B's request pending: no stale A value may be rendered even for one frame.
  let finishB!: (value: string) => void;
  fetchAccounts.mockImplementation(() => new Promise(resolve => { finishB = resolve; }));
  act(() => identify('b'));
  expect(screen.queryByText('tenant A private credential')).not.toBeInTheDocument();
  expect(currentClient!).not.toBe(retired);
  await waitFor(() => expect(fetchAccounts).toHaveBeenCalledTimes(2));
  await act(async () => finishB('tenant B accounts'));
  expect(await screen.findByText('tenant B accounts')).toBeInTheDocument();
  // A late completion writing to a retained old cache cannot contaminate B.
  act(() => retired.setQueryData(['accounts'], 'late tenant A credential'));
  expect(screen.queryByText('late tenant A credential')).not.toBeInTheDocument();
});
