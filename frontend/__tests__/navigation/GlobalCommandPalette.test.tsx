import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { GlobalCommandPalette } from '@/src/features/navigation/GlobalCommandPalette';
import { useCommandPaletteStore } from '@/src/features/navigation/commandPaletteStore';
import { SPHERE_NAV_GROUPS } from '@/src/features/navigation/navigationCatalog';
import userEvent from '@testing-library/user-event';
import { registerWorkspaceLeaveGuard } from '@/src/features/navigation/workspaceNavigationGuard';

const mockPush = jest.fn();
let mockCanAccessRoute = (_path: string) => true;
// Keep this real module's identity consistent with suites that import it
// without a mock; virtual mocks are only for modules absent from the project.
jest.mock('@/src/features/access/Capabilities', () => ({
  useCapabilities: () => ({ canAccessRoute: (path: string) => mockCanAccessRoute(path) }),
}));
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));

describe('GlobalCommandPalette', () => {
  it.each(['Реестр устройств', 'Открыть мониторинг VPN', 'Открыть конструктор скриптов'])('honors the active workspace guard for %s', async label => {
    const guard = jest.fn(() => false); const unregister = registerWorkspaceLeaveGuard(guard);
    try {
      render(<GlobalCommandPalette />); await act(async () => useCommandPaletteStore.getState().open());
      fireEvent.click(screen.getByRole('option', { name: label }));
      expect(guard).toHaveBeenCalledTimes(1); expect(mockPush).not.toHaveBeenCalled();
      expect(useCommandPaletteStore.getState().isOpen).toBe(true);
      guard.mockReturnValue(true); fireEvent.click(screen.getByRole('option', { name: label }));
      expect(mockPush).toHaveBeenCalledTimes(1); expect(useCommandPaletteStore.getState().isOpen).toBe(false);
    } finally { unregister(); }
  });
  beforeAll(() => {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    Element.prototype.scrollIntoView = jest.fn();
  });

  beforeEach(() => {
    mockCanAccessRoute = () => true;
    useCommandPaletteStore.getState().close();
    mockPush.mockReset();
  });

  it('removes denied routes and quick actions while preserving appearance settings', async () => {
    mockCanAccessRoute = path => path === '/devices' || path === '/settings';
    render(<GlobalCommandPalette />);
    await act(async () => useCommandPaletteStore.getState().open());
    expect(screen.queryByRole('option', { name: 'Пользователи' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Открыть мониторинг VPN' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Открыть конструктор скриптов' })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Тема и плотность интерфейса' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('option', { name: 'Реестр устройств' }));
    expect(mockPush).toHaveBeenLastCalledWith('/devices');
  });

  it('opens from the keyboard shortcut, navigates, then closes', async () => {
    render(<GlobalCommandPalette />);

    fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
    expect(await screen.findByRole('dialog', { name: 'Поиск и команды Sphere' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('option', { name: 'Реестр устройств' }));

    expect(mockPush).toHaveBeenCalledWith('/devices');
    await waitFor(() => expect(useCommandPaletteStore.getState().isOpen).toBe(false));
    expect(screen.queryByRole('dialog', { name: 'Поиск и команды Sphere' })).not.toBeInTheDocument();
  });

  it('opens real appearance settings from the command list', async () => {
    useCommandPaletteStore.getState().open();
    render(<GlobalCommandPalette />);

    expect(screen.queryByRole('heading', { name: 'Оформление интерфейса' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('option', { name: 'Тема и плотность интерфейса' }));

    expect(await screen.findByRole('heading', { name: 'Оформление интерфейса' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Компактная/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Закрыть настройки' })).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole('dialog', { name: 'Поиск и команды Sphere' }), { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Оформление интерфейса' })).not.toBeInTheDocument());
    expect(screen.getByRole('dialog', { name: 'Поиск и команды Sphere' })).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole('dialog', { name: 'Поиск и команды Sphere' }), { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Поиск и команды Sphere' })).not.toBeInTheDocument());
  });

  it('sends quick actions to working feature pages', async () => {
    useCommandPaletteStore.getState().open();
    render(<GlobalCommandPalette />);

    fireEvent.click(screen.getByRole('option', { name: 'Открыть мониторинг VPN' }));
    expect(mockPush).toHaveBeenLastCalledWith('/vpn');

    await act(async () => useCommandPaletteStore.getState().open());
    fireEvent.click(await screen.findByRole('option', { name: 'Открыть конструктор скриптов' }));
    expect(mockPush).toHaveBeenLastCalledWith('/scripts/builder');
  });

  it('exposes every sidebar route and sends each option to its canonical destination', async () => {
    render(<GlobalCommandPalette />);
    const items = SPHERE_NAV_GROUPS.flatMap(group => group.items);
    expect(items).toHaveLength(22);
    for (const { href, label } of items) {
      await act(async () => useCommandPaletteStore.getState().open());
      const name = href === '/devices' ? 'Реестр устройств' : href === '/dashboard' ? 'Обзор парка' : label;
      fireEvent.click(await screen.findByRole('option', { name }));
      expect(mockPush).toHaveBeenLastCalledWith(href);
      expect(useCommandPaletteStore.getState().isOpen).toBe(false);
    }
  });

  it('isolates background controls and restores the actual opener on close', async () => {
    render(<><button onClick={() => useCommandPaletteStore.getState().open()}>Открыть поиск</button><GlobalCommandPalette /></>);
    const opener = screen.getByRole('button', { name: 'Открыть поиск' });
    await userEvent.click(opener);
    const dialog = await screen.findByRole('dialog', { name: 'Поиск и команды Sphere' });
    expect(opener.closest('[aria-hidden="true"]')).not.toBeNull();
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Поиск по разделам и командам' })).toHaveFocus());
    fireEvent.keyDown(dialog, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(opener).toHaveFocus());
  });
});
