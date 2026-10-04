import { fireEvent, render, screen } from '@testing-library/react';
import { AppearanceDrawer } from '@/src/features/preferences/AppearanceDrawer';
import { useThemeStore } from '@/src/shared/store/themeStore';
import { useUIStore } from '@/src/shared/store/useUIStore';

describe('AppearanceDrawer', () => {
  beforeEach(() => {
    useThemeStore.setState({ theme: 'light-corporate', density: 'cozy' });
    useUIStore.setState({ theme: 'light', accentColor: 'emerald', fontSize: 'base', density: 'comfortable' });
  });

  it('exposes saved themes, accent, font scale, and density as real settings', () => {
    const onClose = jest.fn();
    render(<AppearanceDrawer open onClose={onClose} />);

    expect(screen.getByRole('dialog', { name: 'Внешний вид' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Светлая/ })).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByRole('button', { name: /Тёмная/ }));
    expect(useThemeStore.getState().theme).toBe('neo-dark');
    expect(useUIStore.getState().theme).toBe('dark');

    fireEvent.click(screen.getByRole('button', { name: 'Крупный' }));
    expect(useUIStore.getState().fontSize).toBe('lg');

    fireEvent.click(screen.getByRole('button', { name: /Свободная/ }));
    expect(useThemeStore.getState().density).toBe('spacious');
    expect(useUIStore.getState().density).toBe('spacious');

    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
