import { create } from 'zustand';
import { persist } from 'zustand/middleware';

type Theme = 'dark' | 'light' | 'system';
type AccentColor = 'violet' | 'blue' | 'emerald' | 'rose' | 'amber';
type Density = 'compact' | 'comfortable' | 'spacious';
type FontSize = 'sm' | 'base' | 'lg';

interface UIState {
    theme: Theme;
    accentColor: AccentColor;
    density: Density;
    fontSize: FontSize;
    sidebarExpanded: boolean;

    setTheme: (theme: Theme) => void;
    setAccentColor: (color: AccentColor) => void;
    setDensity: (density: Density) => void;
    setFontSize: (size: FontSize) => void;
    toggleSidebar: () => void;
}

export const useUIStore = create<UIState>()(
    persist(
        (set) => ({
            theme: 'dark',
            accentColor: 'violet',
            density: 'compact',
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
