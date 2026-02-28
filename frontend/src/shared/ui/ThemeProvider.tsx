'use client';

import { useEffect } from 'react';
import { useThemeStore, ThemeType, DensityType } from '@/src/shared/store/themeStore';

const THEMES: Record<ThemeType, Record<string, string>> = {
    'neo-dark': {
        '--background': '0 0% 2%', // #050505
        '--foreground': '0 0% 98%',
        '--card': '0 0% 4%', // Slightly lighter than bg
        '--card-foreground': '0 0% 98%',
        '--popover': '0 0% 4%',
        '--popover-foreground': '0 0% 98%',
        '--primary': '0 0% 98%',
        '--primary-foreground': '0 0% 9%',
        '--secondary': '0 0% 10%',
        '--secondary-foreground': '0 0% 90%',
        '--muted': '0 0% 10%',
        '--muted-foreground': '0 0% 60%',
        '--border': '0 0% 15%',
        '--input': '0 0% 15%',
        '--ring': '217 91% 60%',
        '--success': '142 72% 29%',
        '--warning': '38 92% 50%',
        '--destructive': '0 84% 60%',
    },
    'matrix-green': {
        '--background': '120 100% 2%', // Very dark green #000A00
        '--foreground': '120 100% 40%', // Hacker green #00CC00
        '--card': '120 100% 4%',
        '--card-foreground': '120 100% 40%',
        '--popover': '120 100% 4%',
        '--popover-foreground': '120 100% 40%',
        '--primary': '120 100% 50%', // Bright green #00FF00
        '--primary-foreground': '120 100% 2%',
        '--secondary': '120 100% 6%',
        '--secondary-foreground': '120 100% 40%',
        '--muted': '120 100% 6%',
        '--muted-foreground': '120 100% 25%',
        '--border': '120 100% 15%',
        '--input': '120 100% 15%',
        '--ring': '120 100% 50%',
        '--success': '120 100% 50%',
        '--warning': '60 100% 50%',
        '--destructive': '0 100% 50%',
    },
    'deep-space': {
        '--background': '240 50% 4%', // Very dark blue #05050F
        '--foreground': '210 50% 90%', // Light blueish white
        '--card': '240 50% 6%',
        '--card-foreground': '210 50% 90%',
        '--popover': '240 50% 6%',
        '--popover-foreground': '210 50% 90%',
        '--primary': '210 100% 60%', // Sci-fi blue
        '--primary-foreground': '240 50% 4%',
        '--secondary': '240 30% 10%',
        '--secondary-foreground': '210 50% 90%',
        '--muted': '240 30% 10%',
        '--muted-foreground': '210 30% 60%',
        '--border': '240 30% 20%',
        '--input': '240 30% 20%',
        '--ring': '210 100% 60%',
        '--success': '160 80% 40%',
        '--warning': '40 90% 60%',
        '--destructive': '350 80% 60%',
    },
    'light-corporate': {
        '--background': '210 40% 98%', // Slate 50 - Very light blue-gray background
        '--foreground': '222 47% 11%', // Slate 900 - Deep crisp text
        '--card': '0 0% 100%', // Pure White for cards
        '--card-foreground': '222 47% 11%',
        '--popover': '0 0% 100%',
        '--popover-foreground': '222 47% 11%',
        '--primary': '221 83% 53%', // Rich corporate blue
        '--primary-foreground': '210 40% 98%',
        '--secondary': '214 32% 91%', // Slate 200 - subtle contrast for sidebar/hover
        '--secondary-foreground': '222 47% 11%',
        '--muted': '214 32% 91%', // Slate 200 - stronger than background for inputs/badges
        '--muted-foreground': '215 16% 47%', // Slate 500 - legible gray text
        '--border': '214 32% 80%', // Slate 300 - Visible but subtle borders
        '--input': '214 32% 91%', // Slate 200 input backgrounds
        '--ring': '221 83% 53%', // Link outline ring to primary
        '--success': '142 70% 35%',
        '--warning': '38 92% 45%', // Darker warning for light theme
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
        root.classList.remove('matrix-mode', 'light-mode', 'space-mode', 'dark');

        // Base dark mode handling (neo-dark, matrix-green, deep-space are dark themes)
        if (theme !== 'light-corporate') {
            root.classList.add('dark');
        }

        if (theme === 'matrix-green') root.classList.add('matrix-mode');
        if (theme === 'light-corporate') root.classList.add('light-mode');
        if (theme === 'deep-space') root.classList.add('space-mode');

    }, [theme, density]);

    return <>{children}</>;
}
