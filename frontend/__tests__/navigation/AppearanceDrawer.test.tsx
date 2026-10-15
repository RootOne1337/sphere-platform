import { fireEvent, render, screen } from '@testing-library/react';
import { AppearanceDrawer } from '@/src/features/preferences/AppearanceDrawer';
import { useThemeStore } from '@/src/shared/store/themeStore';
import { useUIStore } from '@/src/shared/store/useUIStore';

describe('AppearanceDrawer', () => {
  beforeEach(() => {
    useThemeStore.setState({ theme: 'light-corporate', density: 'cozy' });
    useUIStore.setState({ theme: 'light', accentColor: 'emerald', fontSize: 'base', density: 'comfortable', surfaceStyle: 'glass', glassStrength: 'balanced', motionMode: 'system', inspectorMode: 'modal' });
  });

  it('exposes saved themes, accent, font scale, and density as real settings', () => {
    const onClose = jest.fn();
    render(<AppearanceDrawer open onClose={onClose} />);

    expect(screen.getByRole('dialog', { name: 'Внешний вид' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Светлая/ })).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByRole('button', { name: /Тёмная/ }));
    expect(useThemeStore.getState().theme).toBe('neo-dark');
    expect(useUIStore.getState().theme).toBe('dark');

    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Компоновка' }), { button: 0, ctrlKey: false });
    fireEvent.click(screen.getByRole('button', { name: 'Крупный' }));
    expect(useUIStore.getState().fontSize).toBe('lg');

    fireEvent.click(screen.getByRole('button', { name: /Свободная/ }));
    expect(useThemeStore.getState().density).toBe('spacious');
    expect(useUIStore.getState().density).toBe('spacious');

    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

it('applies a recommended glass look without resetting text size, density or inspector mode', () => {
  useThemeStore.setState({ density: 'compact' });
  useUIStore.setState({ fontSize: 'lg', inspectorMode: 'drawer' });
  render(<AppearanceDrawer open onClose={() => undefined} />);
  fireEvent.click(screen.getByRole('button', { name: /^Песочное стекло/ }));
  expect(useThemeStore.getState()).toMatchObject({ theme: 'sandstone', density: 'compact' });
  expect(useUIStore.getState()).toMatchObject({ surfaceStyle: 'glass', glassStrength: 'vivid', accentColor: 'theme', fontSize: 'lg', inspectorMode: 'drawer' });
  fireEvent.click(screen.getByRole('button', { name: 'Матовые' }));
  expect(useThemeStore.getState().theme).toBe('sandstone');
  expect(useUIStore.getState().surfaceStyle).toBe('solid');
});

it('exposes persistent motion and card presentation controls independently of styling', () => {
  render(<AppearanceDrawer open onClose={() => undefined} />);
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'Компоновка' }), { button: 0, ctrlKey: false });
  fireEvent.click(screen.getByRole('button', { name: 'Минимальные' }));
  fireEvent.click(screen.getByRole('button', { name: 'Панель справа' }));
  expect(useUIStore.getState()).toMatchObject({ motionMode: 'reduced', inspectorMode: 'drawer' });
  fireEvent.click(screen.getByRole('button', { name: 'Сбросить настройки' }));
  expect(useUIStore.getState()).toMatchObject({ motionMode: 'system', inspectorMode: 'modal', glassStrength: 'balanced' });
});
