import { applyTheme, themeBootstrapScript, THEMES } from '@/src/shared/theme';
import { useThemeStore } from '@/src/shared/store/themeStore';

const bootstrap = () => { new Function(themeBootstrapScript)(); };
beforeEach(() => { localStorage.clear(); document.documentElement.removeAttribute('style'); document.documentElement.className = ''; });
it('starts in dark without stored preferences', () => {
  bootstrap();
  expect(document.documentElement.classList.contains('dark')).toBe(true);
  expect(document.documentElement.style.getPropertyValue('--background')).toBe(THEMES['neo-dark']['--background']);
  expect(document.documentElement.style.colorScheme).toBe('dark');
});
it('honors an explicitly saved light theme and density before paint and after hydration', async () => {
  localStorage.setItem('sphere-theme-preferences', JSON.stringify({ state: { theme: 'light-corporate', density: 'compact' }, version: 0 }));
  bootstrap();
  expect(document.documentElement.classList.contains('light-mode')).toBe(true);
  expect(document.documentElement.style.getPropertyValue('--font-size-base')).toBe('85%');
  await useThemeStore.persist.rehydrate();
  expect(useThemeStore.getState().theme).toBe('light-corporate');
  expect(useThemeStore.getState().density).toBe('compact');
});
it.each(['bad JSON', JSON.stringify({ state: { theme: 'unknown', density: '__proto__' } })])('falls back for invalid stored preferences', async value => {
  localStorage.setItem('sphere-theme-preferences', value);
  bootstrap();
  expect(document.documentElement.classList.contains('dark')).toBe(true);
});
it('resets every semantic color on switching from light to dark and back', () => {
  applyTheme(document.documentElement, 'light-corporate', 'cozy');
  applyTheme(document.documentElement, 'neo-dark', 'cozy');
  expect(document.documentElement.style.getPropertyValue('--accent')).toBe(THEMES['neo-dark']['--accent']);
  applyTheme(document.documentElement, 'light-corporate', 'cozy');
  expect(document.documentElement.style.getPropertyValue('--primary')).toBe(THEMES['light-corporate']['--primary']);
  expect(document.documentElement.classList.contains('dark')).toBe(false);
});
