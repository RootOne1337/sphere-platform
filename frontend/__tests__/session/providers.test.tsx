import { act, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, useQuery, useQueryClient } from '@tanstack/react-query';
import { Providers } from '@/app/providers';
import { useAuthStore } from '@/lib/store';

let mockReady = true;
let mockPath = '/accounts';
const mockReplace = jest.fn();
jest.mock('next/navigation', () => ({
  usePathname: () => mockPath,
  useRouter: () => ({ replace: mockReplace }),
}));
jest.mock('@/lib/store', () => ({
  ...jest.requireActual('@/lib/store'),
  useInitAuth: () => mockReady,
}));

function identify(org: string) {
  useAuthStore.getState().setAccessToken(`access-${org}`);
  useAuthStore.getState().setUser({ id: `user-${org}`, org_id: org, email: 'audit@example.test', role: 'admin' });
}

beforeEach(() => {
  useAuthStore.getState().logout();
  localStorage.clear();
  mockReady = true;
  mockPath = '/accounts';
  mockReplace.mockClear();
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

it('redirects an authenticated login visit without mounting the form', () => {
  identify('a');
  mockPath = '/login';
  render(<Providers><div>login form</div></Providers>);
  expect(screen.queryByText('login form')).not.toBeInTheDocument();
  expect(mockReplace).toHaveBeenCalledWith('/dashboard');
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
