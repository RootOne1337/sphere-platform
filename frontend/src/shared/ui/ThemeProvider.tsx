'use client';

import { useEffect } from 'react';
import { useThemeStore, ThemeType, DensityType } from '@/src/shared/store/themeStore';

const THEMES: Record<ThemeType, Record<string, string>> = {
    'neo-dark': {
        '--background': '0 0% 2%', // #050505
        '--foreground': '0 0% 98%',
        '--primary': '0 0% 98%',
        '--primary-foreground': '0 0% 9%',
        '--muted': '0 0% 10%',
        '--muted-foreground': '0 0% 60%',
        '--border': '0 0% 15%',
        '--success': '142 72% 29%', // Green
        '--warning': '38 92% 50%', // Orange
        '--destructive': '0 84% 60%', // Red
    },
    'matrix-green': {
        '--background': '120 100% 2%', // Very dark green #000A00
        '--foreground': '120 100% 40%', // Hacker green #00CC00
        '--primary': '120 100% 50%', // Bright green #00FF00
        '--primary-foreground': '120 100% 2%',
        '--muted': '120 100% 6%',
        '--muted-foreground': '120 100% 25%',
        '--border': '120 100% 15%',
        '--success': '120 100% 50%',
        '--warning': '60 100% 50%', // Yellow
        '--destructive': '0 100% 50%', // Red
    },
    'deep-space': {
        '--background': '240 50% 4%', // Very dark blue #05050F
        '--foreground': '210 50% 90%', // Light blueish white
        '--primary': '210 100% 60%', // Sci-fi blue
        '--primary-foreground': '240 50% 4%',
        '--muted': '240 30% 10%',
        '--muted-foreground': '210 30% 60%',
        '--border': '240 30% 20%',
        '--success': '160 80% 40%',
        '--warning': '40 90% 60%',
        '--destructive': '350 80% 60%',
    },
    'light-corporate': {
        '--background': '0 0% 98%',
        '--foreground': '0 0% 10%',
        '--primary': '220 90% 50%', // Corporate Blue
        '--primary-foreground': '0 0% 100%',
        '--muted': '0 0% 92%',
        '--muted-foreground': '0 0% 40%',
        '--border': '0 0% 85%',
        '--success': '142 70% 35%',
        '--warning': '38 92% 50%',
        '--destructive': '0 84% 50%',
    }
};

const DENSITIES: Record<DensityType, Record<string, string>> = {
    'compact': {
        '--radius': '0.125rem', // Sharpest
        '--spacing-base': '0.75', // Scaled down everything 
        '--font-size-base': '85%',
    },
    'cozy': {
        '--radius': '0.25rem', // Standard
        '--spacing-base': '1',
        '--font-size-base': '100%',
    },
    'spacious': {
        '--radius': '0.5rem', // Round
        '--spacing-base': '1.25',
        '--font-size-base': '115%',
    }
};

export function ThemeProvider({ children }: { children: React.ReactNode }) {
    const { theme, density } = useThemeStore();

    useEffect(() => {
        const root = document.documentElement;

        // Apply Theme Colors
        const themeVars = THEMES[theme] || THEMES['neo-dark'];
        Object.entries(themeVars).forEach(([key, value]) => {
            root.style.setProperty(key, value);
        });

        // Apply Density & Scaling Constraints
        const densityVars = DENSITIES[density] || DENSITIES['cozy'];
        Object.entries(densityVars).forEach(([key, value]) => {
            root.style.setProperty(key, value);
        });

        // Optional class toggling for specialized tailwind behavior
        root.classList.remove('matrix-mode', 'light-mode', 'space-mode');
        if (theme === 'matrix-green') root.classList.add('matrix-mode');
        if (theme === 'light-corporate') root.classList.add('light-mode');
        if (theme === 'deep-space') root.classList.add('space-mode');

    }, [theme, density]);

    return <>{children}</>;
}
