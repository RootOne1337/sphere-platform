import { fireEvent, render, screen } from '@testing-library/react';
import { NOCSidebar } from '@/src/features/navigation/NOCSidebar';
import { signOut } from '@/lib/store';

const mockReplace = jest.fn();
let mockPathname = '/devices/device-123';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

jest.mock('next/navigation', () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ replace: mockReplace }),
}));

jest.mock('@/lib/store', () => ({ signOut: jest.fn() }));

const EXPECTED_ROUTES = [
  '/dashboard', '/monitoring', '/devices', '/stream', '/discovery', '/groups', '/locations',
  '/tasks', '/orchestration', '/pipeline-settings', '/accounts', '/scripts',
  '/events', '/event-triggers', '/sessions', '/vpn', '/webhooks',
  '/users', '/audit', '/logs', '/updates', '/settings',
];

beforeEach(() => {
  jest.clearAllMocks();
  mockPathname = '/devices/device-123';
});

it('keeps every existing route reachable in the grouped, collapsed navigation', () => {
  render(<NOCSidebar />);

  const links = screen.getAllByRole('link');
  expect(links.map((link) => link.getAttribute('href'))).toEqual(EXPECTED_ROUTES);
  expect(screen.getByRole('link', { name: 'Парк устройств' })).toHaveAttribute('aria-current', 'page');
  expect(screen.getByRole('button', { name: 'Развернуть навигацию' })).toHaveAttribute('aria-expanded', 'false');
});

it('shows category headings and visible labels when the sidebar expands', () => {
  render(<NOCSidebar />);

  fireEvent.click(screen.getByRole('button', { name: 'Развернуть навигацию' }));

  expect(screen.getByText('Автоматизация')).toBeInTheDocument();
  expect(screen.getByText('События и сеть')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Парк устройств' })).toHaveTextContent('Парк устройств');
  expect(screen.getByRole('button', { name: 'Свернуть навигацию' })).toHaveAttribute('aria-expanded', 'true');
});

it('preserves sign out behavior and closes a mobile menu after navigation', () => {
  const onMobileClose = jest.fn();
  render(<NOCSidebar isMobileOpen onMobileClose={onMobileClose} />);

  fireEvent.click(screen.getByRole('button', { name: 'Выйти' }));
  expect(signOut).toHaveBeenCalledTimes(1);
  expect(mockReplace).toHaveBeenCalledWith('/login');

  fireEvent.click(screen.getByRole('link', { name: 'Задания' }));
  expect(onMobileClose).toHaveBeenCalledTimes(1);
});
