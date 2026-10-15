import { act, render } from '@testing-library/react';
import { ThemeProvider } from '@/src/shared/ui/ThemeProvider';
import { useThemeStore } from '@/src/shared/store/themeStore';
import { useUIStore } from '@/src/shared/store/useUIStore';
import { ACCENT_TOKENS, applyTheme, DENSITIES, resolveAppearance, THEMES, themeBootstrapScript, type AccentColor, type ThemeType } from '@/src/shared/theme';

function luminance(hsl: string) {
  const [h, percentS, percentL] = hsl.split(' ').map(parseFloat);
  const s = percentS / 100; const l = percentL / 100;
  const a = s * Math.min(l, 1 - l);
  return [0, 8, 4].map(n => { const k = (n + h / 30) % 12; const v = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)); return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; })
    .reduce((sum, v, index) => sum + v * [.2126, .7152, .0722][index], 0);
}
function contrast(a: string, b: string) { const x = luminance(a); const y = luminance(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); }

beforeEach(() => {
  localStorage.clear(); document.documentElement.removeAttribute('style'); document.documentElement.className = '';
  useThemeStore.setState({ theme: 'neo-dark', density: 'cozy' });
  useUIStore.setState({ accentColor: 'theme', fontSize: 'base', sidebarMode: 'auto', surfaceStyle: 'glass', glassStrength: 'balanced', motionMode: 'system' });
});

it.each(Object.keys(THEMES) as ThemeType[])('%s keeps ordinary semantic text readable for every selectable accent', theme => {
  for (const accentColor of ['theme', ...Object.keys(ACCENT_TOKENS)] as AccentColor[]) {
    const tokens = resolveAppearance(theme, 'cozy', { accentColor });
    for (const [foreground, background] of [['--foreground', '--background'], ['--card-foreground', '--card'], ['--muted-foreground', '--card'], ['--muted-foreground', '--muted'], ['--primary-foreground', '--primary'], ['--destructive-foreground', '--destructive'], ['--primary', '--card'], ['--accent-foreground', '--accent']]) {
      expect(contrast(tokens[foreground], tokens[background])).toBeGreaterThanOrEqual(4.5);
    }
  }
});

it('uses the same theme + accent + text scale before paint and after hydration, including invalid stored values', () => {
  for (const theme of Object.keys(THEMES) as ThemeType[]) for (const accentColor of ['theme', 'blue', '__proto__']) {
    localStorage.setItem('sphere-theme-preferences', JSON.stringify({ state: { theme, density: 'compact' } }));
    localStorage.setItem('sphere-ui-preferences', JSON.stringify({ state: { accentColor, fontSize: 'lg', surfaceStyle: 'solid' } }));
    new Function(themeBootstrapScript)();
    const before = document.documentElement.style.cssText;
    applyTheme(document.documentElement, theme, 'compact', { accentColor: accentColor === '__proto__' ? 'theme' : accentColor as AccentColor, fontSize: 'lg', surfaceStyle: 'solid' });
    expect(document.documentElement.style.cssText).toBe(before);
    expect(document.documentElement.dataset.surface).toBe('solid');
  }
});

it('keeps accent and text scale when the theme changes and applies density without shrinking text', () => {
  render(<ThemeProvider><div>Workspace</div></ThemeProvider>);
  act(() => useUIStore.getState().setAccentColor('blue'));
  const blue = document.documentElement.style.getPropertyValue('--primary');
  act(() => useThemeStore.getState().setTheme('matrix-green'));
  expect(document.documentElement.style.getPropertyValue('--primary')).toBe(blue);
  act(() => useThemeStore.getState().setDensity('compact'));
  expect(document.documentElement.style.getPropertyValue('--control-height')).toBe(DENSITIES.compact['--control-height']);
  expect(document.documentElement.style.getPropertyValue('--font-size-base')).toBe('100%');
  act(() => useUIStore.getState().setFontSize('lg'));
  expect(document.documentElement.style.getPropertyValue('--font-size-base')).toBe('112.5%');
});

it.each([[true, 'pinned'], [false, 'rail']] as const)('migrates a saved legacy sidebar preference %s without losing other choices', async (sidebarExpanded, expected) => {
  localStorage.setItem('sphere-ui-preferences', JSON.stringify({ state: { sidebarExpanded, accentColor: 'violet', fontSize: 'lg' }, version: 0 }));
  await useUIStore.persist.rehydrate();
  expect(useUIStore.getState().sidebarMode).toBe(expected);
  expect(useUIStore.getState().accentColor).toBe('violet');
  expect(useUIStore.getState().fontSize).toBe('lg');
});

it('rejects corrupt persisted settings without replacing store actions', async () => {
  localStorage.setItem('sphere-ui-preferences', JSON.stringify({ state: { sidebarMode: 'unknown', accentColor: '__proto__', fontSize: 'giant', setAccentColor: 'bad' }, version: 1 }));
  await useUIStore.persist.rehydrate();
  expect(useUIStore.getState().accentColor).toBe('theme');
  expect(useUIStore.getState().fontSize).toBe('base');
  expect(useUIStore.getState().sidebarMode).toBe('auto');
  expect(typeof useUIStore.getState().setAccentColor).toBe('function');
});

it('preserves material intensity and motion before paint, after hydration and from saved version1 settings', async () => {
  localStorage.setItem('sphere-ui-preferences', JSON.stringify({ state: { surfaceStyle: 'glass', glassStrength: 'vivid', motionMode: 'reduced', inspectorMode: 'drawer', accentColor: 'amber' }, version: 1 }));
  localStorage.setItem('sphere-theme-preferences', JSON.stringify({ state: { theme: 'sandstone', density: 'compact' } }));
  new Function(themeBootstrapScript)();
  const before = document.documentElement.style.cssText;
  await useUIStore.persist.rehydrate();
  applyTheme(document.documentElement, 'sandstone', 'compact', useUIStore.getState());
  expect(document.documentElement.style.cssText).toBe(before);
  expect(document.documentElement.dataset.motion).toBe('reduced');
  expect(useUIStore.getState().inspectorMode).toBe('drawer');
  expect(document.documentElement.style.getPropertyValue('--glass-opacity')).toBe('.48');
});

it('rejects untrusted material and motion values while retaining known old preferences', async () => {
  localStorage.setItem('sphere-ui-preferences', JSON.stringify({ state: { surfaceStyle: 'solid', glassStrength: '__proto__', motionMode: 'fast', inspectorMode: 'evil', accentColor: 'blue' }, version: 1 }));
  await useUIStore.persist.rehydrate();
  expect(useUIStore.getState()).toMatchObject({ surfaceStyle: 'solid', glassStrength: 'balanced', motionMode: 'system', inspectorMode: 'modal', accentColor: 'blue' });
});
