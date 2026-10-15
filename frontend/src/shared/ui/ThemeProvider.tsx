'use client';

import { useEffect } from 'react';
import { useThemeStore } from '@/src/shared/store/themeStore';
import { useUIStore } from '@/src/shared/store/useUIStore';
import { applyTheme } from '@/src/shared/theme';

export function ThemeProvider({ children }: { children: React.ReactNode }) {
    const { theme, density } = useThemeStore();
    const { accentColor, fontSize, surfaceStyle } = useUIStore();
    useEffect(() => {
        // Read the current store rather than reapplying an obsolete hydration
        // snapshot over the preference installed by the before-paint bootstrap.
        const current = useThemeStore.getState();
        const options = useUIStore.getState();
        applyTheme(document.documentElement, current.theme, current.density, options);
    }, [theme, density, accentColor, fontSize, surfaceStyle]);
    return <>{children}</>;
}
