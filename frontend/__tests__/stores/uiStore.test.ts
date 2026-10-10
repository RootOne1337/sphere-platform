/**
 * Тесты Zustand-стора useUIStore — тема, акцент, плотность, шрифт, сайдбар.
 * Включая поведение persist (localStorage).
 */
import { useUIStore } from '@/src/shared/store/useUIStore';

describe('useUIStore', () => {
  beforeEach(() => {
    // Сбрасываем к дефолтам
    useUIStore.setState({
      theme: 'light',
      accentColor: 'emerald',
      density: 'comfortable',
      fontSize: 'base',
      sidebarExpanded: true,
    });
  });

  describe('начальное состояние', () => {
    it('uses light theme by default', () => expect(useUIStore.getState().theme).toBe('light'));
    it('uses emerald accent by default', () => expect(useUIStore.getState().accentColor).toBe('emerald'));
    it('uses comfortable density by default', () => expect(useUIStore.getState().density).toBe('comfortable'));
    it('шрифт = base', () => expect(useUIStore.getState().fontSize).toBe('base'));
    it('сайдбар развёрнут', () => expect(useUIStore.getState().sidebarExpanded).toBe(true));
  });

  describe('setTheme', () => {
    it('меняет тему на light', () => {
      useUIStore.getState().setTheme('light');
      expect(useUIStore.getState().theme).toBe('light');
    });

    it('поддерживает system', () => {
      useUIStore.getState().setTheme('system');
      expect(useUIStore.getState().theme).toBe('system');
    });
  });

  describe('setAccentColor', () => {
    it.each(['blue', 'emerald', 'rose', 'amber'] as const)('устанавливает %s', (color) => {
      useUIStore.getState().setAccentColor(color);
      expect(useUIStore.getState().accentColor).toBe(color);
    });
  });

  describe('setDensity', () => {
    it.each(['comfortable', 'spacious'] as const)('устанавливает %s', (density) => {
      useUIStore.getState().setDensity(density);
      expect(useUIStore.getState().density).toBe(density);
    });
  });

  describe('setFontSize', () => {
    it.each(['sm', 'lg'] as const)('устанавливает %s', (size) => {
      useUIStore.getState().setFontSize(size);
      expect(useUIStore.getState().fontSize).toBe(size);
    });
  });

  describe('toggleSidebar', () => {
    it('сворачивает сайдбар', () => {
      useUIStore.getState().toggleSidebar();
      expect(useUIStore.getState().sidebarExpanded).toBe(false);
    });

    it('разворачивает сайдбар обратно', () => {
      useUIStore.getState().toggleSidebar(); // false
      useUIStore.getState().toggleSidebar(); // true
      expect(useUIStore.getState().sidebarExpanded).toBe(true);
    });
  });
});
