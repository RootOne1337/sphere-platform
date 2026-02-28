import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type ThemeType = 'neo-dark' | 'matrix-green' | 'deep-space' | 'light-corporate';
export type DensityType = 'compact' | 'cozy' | 'spacious';

interface ThemeState {
    theme: ThemeType;
    density: DensityType;
    setTheme: (theme: ThemeType) => void;
    setDensity: (density: DensityType) => void;
}

export const useThemeStore = create<ThemeState>()(
    persist(
        (set) => ({
            theme: 'neo-dark',
            density: 'cozy',
            setTheme: (theme) => set({ theme }),
            setDensity: (density) => set({ density }),
        }),
        {
            name: 'sphere-theme-preferences',
        }
    )
);
