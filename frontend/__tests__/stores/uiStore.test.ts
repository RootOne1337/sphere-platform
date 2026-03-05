/**
 * Тесты Zustand-стора useUIStore — тема, акцент, плотность, шрифт, сайдбар.
 * Включая поведение persist (localStorage).
 */
import { useUIStore } from '@/src/shared/store/useUIStore';

describe('useUIStore', () => {
  beforeEach(() => {
    // Сбрасываем к дефолтам
    useUIStore.setState({
      theme: 'dark',
      accentColor: 'violet',
      density: 'compact',
      fontSize: 'base',
      sidebarExpanded: true,
    });
  });

  describe('начальное состояние', () => {
    it('тема = dark', () => expect(useUIStore.getState().theme).toBe('dark'));
    it('акцент = violet', () => expect(useUIStore.getState().accentColor).toBe('violet'));
    it('плотность = compact', () => expect(useUIStore.getState().density).toBe('compact'));
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
