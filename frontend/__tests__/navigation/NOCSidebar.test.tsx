import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { NOCSidebar } from '@/src/features/navigation/NOCSidebar';
import { signOut } from '@/lib/store';
import { useUIStore } from '@/src/shared/store/useUIStore';

const mockReplace = jest.fn();
let mockPathname = '/devices/device-123';
let mockDesktop = true;
let mockBreakpointChange: (() => void) | undefined;

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, onClick, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props} onClick={(event) => { event.preventDefault(); onClick?.(event); }}>{children}</a>
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
  mockDesktop = true;
  mockBreakpointChange = undefined;
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: jest.fn(() => ({
    get matches() { return mockDesktop; },
    addEventListener: (_type: string, listener: () => void) => { mockBreakpointChange = listener; },
    removeEventListener: jest.fn(),
  })) });
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
  mockDesktop = false;
  const onMobileClose = jest.fn();
  render(<NOCSidebar isMobileOpen onMobileClose={onMobileClose} />);

  fireEvent.click(screen.getByRole('button', { name: 'Выйти' }));
  expect(signOut).toHaveBeenCalledTimes(1);
  expect(mockReplace).toHaveBeenCalledWith('/login');

  fireEvent.click(screen.getByRole('link', { name: 'Задания' }));
  expect(onMobileClose).toHaveBeenCalledTimes(1);
});

function MobileNavigation() {
  const [open, setOpen] = useState(false);
  return <><button onClick={() => setOpen(true)}>Открыть меню</button><button>Фоновое действие</button><NOCSidebar isMobileOpen={open} onMobileClose={() => setOpen(false)} /></>;
}

it('does not mount focusable mobile links while its menu is closed', () => {
  mockDesktop = false;
  render(<MobileNavigation />);
  expect(screen.queryByRole('link', { name: 'Парк устройств', hidden: true })).not.toBeInTheDocument();
  expect(screen.queryByRole('navigation', { hidden: true })).not.toBeInTheDocument();
});

it('traps mobile focus, hides the background and restores the opener on Escape', async () => {
  mockDesktop = false;
  render(<MobileNavigation />);
  const opener = screen.getByRole('button', { name: 'Открыть меню' });
  await userEvent.click(opener);
  const dialog = await screen.findByRole('dialog', { name: 'Меню навигации Sphere' });
  expect(dialog).toHaveAttribute('aria-modal', 'true');
  expect(opener.closest('[aria-hidden="true"]')).not.toBeNull();
  const first = within(dialog).getByRole('link', { name: 'Sphere — главная' });
  await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Закрыть меню навигации' })).toHaveFocus());
  await userEvent.tab({ shift: true });
  await waitFor(() => expect(first).toHaveFocus());
  await userEvent.tab({ shift: true });
  expect(within(dialog).getByRole('button', { name: 'Выйти' })).toHaveFocus();
  await userEvent.tab();
  expect(first).toHaveFocus();
  fireEvent.keyDown(dialog, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  await waitFor(() => expect(opener).toHaveFocus());
});

it('keeps mobile labels visible even when the desktop preference is collapsed', async () => {
  mockDesktop = false;
  useUIStore.setState({ sidebarExpanded: false });
  render(<MobileNavigation />);
  await userEvent.click(screen.getByRole('button', { name: 'Открыть меню' }));
  expect(screen.getByRole('link', { name: 'Парк устройств' })).toHaveTextContent('Парк устройств');
  expect(screen.queryByRole('button', { name: 'Развернуть меню', hidden: true })).not.toBeInTheDocument();
});

it('reconciles mobile and desktop navigation at the actual breakpoint', async () => {
  mockDesktop = false;
  render(<MobileNavigation />);
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  mockDesktop = true;
  fireEvent(window, new Event('resize'));
  // MatchMedia owns this change, rather than polling window dimensions.
  await act(async () => { mockBreakpointChange?.(); });
  expect(screen.getByRole('navigation', { name: 'Основная навигация' })).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
