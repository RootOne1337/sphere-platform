import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type UIThemeMode = 'dark' | 'light' | 'system';
export type AccentColor = 'violet' | 'blue' | 'emerald' | 'rose' | 'amber';
export type UIDensity = 'compact' | 'comfortable' | 'spacious';
export type FontScale = 'sm' | 'base' | 'lg';

interface UIState {
    theme: UIThemeMode;
    accentColor: AccentColor;
    density: UIDensity;
    fontSize: FontScale;
    sidebarExpanded: boolean;

    setTheme: (theme: UIThemeMode) => void;
    setAccentColor: (color: AccentColor) => void;
    setDensity: (density: UIDensity) => void;
    setFontSize: (size: FontScale) => void;
    toggleSidebar: () => void;
}

export const useUIStore = create<UIState>()(
    persist(
        (set) => ({
            theme: 'light',
            accentColor: 'emerald',
            density: 'comfortable',
            fontSize: 'base',
            sidebarExpanded: true,

            setTheme: (theme) => set({ theme }),
            setAccentColor: (color) => set({ accentColor: color }),
            setDensity: (density) => set({ density }),
            setFontSize: (size) => set({ fontSize: size }),
            toggleSidebar: () => set((state) => ({ sidebarExpanded: !state.sidebarExpanded })),
        }),
        {
            name: 'sphere-ui-preferences',
        }
    )
);
