import { useThemeStore } from '@/src/shared/store/themeStore';
import { useUIStore, type InspectorMode, type SidebarMode } from '@/src/shared/store/useUIStore';
import {
  isAccent, isDensity, isFontScale, isGlassStrength, isLightTheme, isTheme,
  type AccentColor, type DensityType, type FontScale, type GlassStrength, type MotionMode,
  type SurfaceStyle, type ThemeType,
} from '@/src/shared/theme';

export type Appearance = {
  palette: ThemeType;
  density: DensityType;
  accent_color: AccentColor;
  font_size: FontScale;
  sidebar_mode: SidebarMode;
  inspector_mode: InspectorMode;
  surface_style: SurfaceStyle;
  glass_strength: GlassStrength;
  motion_mode: MotionMode;
};
export type PreferenceProfile = {
  schema_version: 1;
  org_id: string;
  user_id: string;
  revision: number;
  appearance: Appearance;
};
export const DEFAULT_APPEARANCE: Appearance = {
  palette: 'neo-dark', density: 'cozy', accent_color: 'theme', font_size: 'base', sidebar_mode: 'auto',
  inspector_mode: 'modal', surface_style: 'glass', glass_strength: 'balanced', motion_mode: 'system',
};

export function readAppearance(): Appearance {
  const theme = useThemeStore.getState();
  const ui = useUIStore.getState();
  return {
    palette: theme.theme, density: theme.density, accent_color: ui.accentColor, font_size: ui.fontSize,
    sidebar_mode: ui.sidebarMode, inspector_mode: ui.inspectorMode, surface_style: ui.surfaceStyle,
    glass_strength: ui.glassStrength, motion_mode: ui.motionMode,
  };
}

export function applyAppearance(value: Appearance): void {
  useThemeStore.setState({ theme: value.palette, density: value.density });
  useUIStore.setState({
    theme: isLightTheme(value.palette) ? 'light' : 'dark', density: value.density === 'cozy' ? 'comfortable' : value.density,
    accentColor: value.accent_color, fontSize: value.font_size, sidebarMode: value.sidebar_mode,
    sidebarExpanded: value.sidebar_mode !== 'rail', inspectorMode: value.inspector_mode,
    surfaceStyle: value.surface_style, glassStrength: value.glass_strength, motionMode: value.motion_mode,
  });
}

export function appearanceChanges(previous: Appearance, next: Appearance): Partial<Appearance> {
  const keys = Object.keys(DEFAULT_APPEARANCE) as (keyof Appearance)[];
  return Object.fromEntries(keys.filter(key => previous[key] !== next[key]).map(key => [key, next[key]]));
}

export function parsePreferenceProfile(data: unknown, org: string, user: string): PreferenceProfile {
  const profile = data as Partial<PreferenceProfile> | null;
  const a = profile?.appearance;
  if (profile?.schema_version !== 1 || profile.org_id !== org || profile.user_id !== user
    || typeof profile.revision !== 'number' || !Number.isSafeInteger(profile.revision) || profile.revision < 0
    || !a || !isTheme(a.palette) || !isDensity(a.density) || !isAccent(a.accent_color)
    || !isFontScale(a.font_size) || !isGlassStrength(a.glass_strength)
    || !['auto', 'pinned', 'rail'].includes(a.sidebar_mode) || !['modal', 'drawer'].includes(a.inspector_mode)
    || !['solid', 'glass'].includes(a.surface_style) || !['system', 'reduced'].includes(a.motion_mode)) {
    throw new Error('Invalid appearance profile');
  }
  const keys = Object.keys(DEFAULT_APPEARANCE) as (keyof Appearance)[];
  return {
    schema_version: 1, org_id: org, user_id: user, revision: profile.revision,
    appearance: Object.fromEntries(keys.map(key => [key, a[key]])) as Appearance,
  };
}
