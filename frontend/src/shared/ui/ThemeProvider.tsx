'use client';

import { useEffect } from 'react';
import { useThemeStore } from '@/src/shared/store/themeStore';
import { applyTheme } from '@/src/shared/theme';

export function ThemeProvider({ children }: { children: React.ReactNode }) {
    const { theme, density } = useThemeStore();
    useEffect(() => {
        // Read the current store rather than reapplying an obsolete hydration
        // snapshot over the preference installed by the before-paint bootstrap.
        const current = useThemeStore.getState();
        applyTheme(document.documentElement, current.theme, current.density);
    }, [theme, density]);
    return <>{children}</>;
}
