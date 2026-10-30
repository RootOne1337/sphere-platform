import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { DEFAULT_THEME, DEFAULT_DENSITY, isTheme, isDensity, type ThemeType, type DensityType } from '@/src/shared/theme';

export type { ThemeType, DensityType } from '@/src/shared/theme';

interface ThemeState {
    theme: ThemeType;
    density: DensityType;
    setTheme: (theme: ThemeType) => void;
    setDensity: (density: DensityType) => void;
}

export const useThemeStore = create<ThemeState>()(
    persist(
        (set) => ({
            theme: DEFAULT_THEME,
            density: DEFAULT_DENSITY,
            setTheme: (theme) => set({ theme }),
            setDensity: (density) => set({ density }),
        }),
        {
            name: 'sphere-theme-preferences',
            partialize: state => ({ theme: state.theme, density: state.density }),
            merge: (persisted, current) => {
                const value = persisted && typeof persisted === 'object' ? persisted as Partial<ThemeState> : {};
                return { ...current, theme: isTheme(value.theme) ? value.theme : DEFAULT_THEME,
                    density: isDensity(value.density) ? value.density : DEFAULT_DENSITY };
            },
        }
    )
);
