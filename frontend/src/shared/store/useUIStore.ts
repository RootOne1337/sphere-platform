import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { isAccent, isFontScale, type AccentColor, type FontScale, type SurfaceStyle } from '@/src/shared/theme';

export type UIThemeMode = 'dark' | 'light' | 'system';
export type { AccentColor, FontScale, SurfaceStyle } from '@/src/shared/theme';
export type UIDensity = 'compact' | 'comfortable' | 'spacious';
export type SidebarMode = 'auto' | 'pinned' | 'rail';

interface UIState {
    theme: UIThemeMode;
    accentColor: AccentColor;
    density: UIDensity;
    fontSize: FontScale;
    sidebarExpanded: boolean;
    sidebarMode: SidebarMode;
    surfaceStyle: SurfaceStyle;

    setTheme: (theme: UIThemeMode) => void;
    setAccentColor: (color: AccentColor) => void;
    setDensity: (density: UIDensity) => void;
    setFontSize: (size: FontScale) => void;
    toggleSidebar: () => void;
    setSidebarMode: (mode: SidebarMode) => void;
    setSurfaceStyle: (style: SurfaceStyle) => void;
}

export const useUIStore = create<UIState>()(
    persist(
        (set) => ({
            theme: 'dark',
            accentColor: 'theme',
            density: 'comfortable',
            fontSize: 'base',
            sidebarExpanded: true,
            sidebarMode: 'auto',
            surfaceStyle: 'glass',

            setTheme: (theme) => set({ theme }),
            setAccentColor: (color) => set({ accentColor: color }),
            setDensity: (density) => set({ density }),
            setFontSize: (size) => set({ fontSize: size }),
            toggleSidebar: () => set((state) => ({ sidebarExpanded: !state.sidebarExpanded, sidebarMode: state.sidebarExpanded ? 'rail' : 'pinned' })),
            setSidebarMode: (sidebarMode) => set({ sidebarMode, sidebarExpanded: sidebarMode !== 'rail' }),
            setSurfaceStyle: (surfaceStyle) => set({ surfaceStyle }),
        }),
        {
            name: 'sphere-ui-preferences',
            version: 1,
            partialize: ({ theme, accentColor, density, fontSize, sidebarExpanded, sidebarMode, surfaceStyle }) =>
                ({ theme, accentColor, density, fontSize, sidebarExpanded, sidebarMode, surfaceStyle }),
            migrate: (persisted) => {
                const value = persisted && typeof persisted === 'object' ? persisted as Partial<UIState> : {};
                return { theme: value.theme ?? 'dark', accentColor: value.accentColor ?? 'theme', density: value.density ?? 'comfortable',
                    fontSize: value.fontSize ?? 'base', surfaceStyle: value.surfaceStyle ?? 'glass',
                    sidebarExpanded: value.sidebarExpanded !== false,
                    sidebarMode: value.sidebarMode ?? (value.sidebarExpanded === false ? 'rail' : value.sidebarExpanded === true ? 'pinned' : 'auto') };
            },
            merge: (persisted, current) => {
                const value = persisted && typeof persisted === 'object' ? persisted as Partial<UIState> : {};
                const sidebarMode = ['auto', 'pinned', 'rail'].includes(value.sidebarMode ?? '') ? value.sidebarMode! : current.sidebarMode;
                return { ...current,
                    theme: ['dark', 'light', 'system'].includes(value.theme ?? '') ? value.theme! : current.theme,
                    accentColor: isAccent(value.accentColor) ? value.accentColor : current.accentColor,
                    fontSize: isFontScale(value.fontSize) ? value.fontSize : current.fontSize,
                    density: ['compact', 'comfortable', 'spacious'].includes(value.density ?? '') ? value.density! : current.density,
                    sidebarMode, sidebarExpanded: sidebarMode !== 'rail',
                    surfaceStyle: value.surfaceStyle === 'solid' ? 'solid' : 'glass',
                };
            },
        }
    )
);
