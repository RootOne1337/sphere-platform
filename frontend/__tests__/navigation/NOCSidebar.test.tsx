import { fireEvent, render, screen, within } from '@testing-library/react';
import { NOCSidebar } from '@/src/features/navigation/NOCSidebar';
import { signOut } from '@/lib/store';
import { useUIStore } from '@/src/shared/store/useUIStore';

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
  useUIStore.setState({ sidebarExpanded: true });
});

it('keeps every existing route visible in the expanded admin navigation', () => {
  render(<NOCSidebar />);

  const links = within(screen.getByRole('navigation', { name: 'Основная навигация' })).getAllByRole('link');
  expect(links.map((link) => link.getAttribute('href'))).toEqual(EXPECTED_ROUTES);
  expect(screen.getByRole('link', { name: 'Парк устройств' })).toHaveAttribute('aria-current', 'page');
  expect(screen.getByRole('button', { name: 'Свернуть меню', hidden: true })).toHaveAttribute('aria-expanded', 'true');
});

it('shows section headings and persists the collapsed state when toggled', () => {
  render(<NOCSidebar />);

  expect(screen.getByText('Автоматизация')).toBeInTheDocument();
  expect(screen.getByText('События и сеть')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Парк устройств' })).toHaveTextContent('Парк устройств');

  fireEvent.click(screen.getByRole('button', { name: 'Свернуть меню', hidden: true }));
  expect(screen.getByRole('button', { name: 'Развернуть меню', hidden: true })).toHaveAttribute('aria-expanded', 'false');
  expect(useUIStore.getState().sidebarExpanded).toBe(false);
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
