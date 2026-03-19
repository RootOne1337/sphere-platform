/**
 * Тесты Zustand-стора useThemeStore — темы приложения, плотность.
 */
import { useThemeStore } from '@/src/shared/store/themeStore';

describe('useThemeStore', () => {
  beforeEach(() => {
    useThemeStore.setState({ theme: 'neo-dark', density: 'cozy' });
  });

  describe('начальное состояние', () => {
    it('theme = neo-dark', () => expect(useThemeStore.getState().theme).toBe('neo-dark'));
    it('density = cozy', () => expect(useThemeStore.getState().density).toBe('cozy'));
  });

  describe('setTheme', () => {
    it.each([
      'neo-dark', 'matrix-green', 'deep-space', 'light-corporate',
    ] as const)('устанавливает тему %s', (theme) => {
      useThemeStore.getState().setTheme(theme);
      expect(useThemeStore.getState().theme).toBe(theme);
    });
  });

  describe('setDensity', () => {
    it.each(['compact', 'cozy', 'spacious'] as const)('устанавливает плотность %s', (density) => {
      useThemeStore.getState().setDensity(density);
      expect(useThemeStore.getState().density).toBe(density);
    });
  });
});
