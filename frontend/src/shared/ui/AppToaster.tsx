'use client';

import { Toaster } from 'sonner';
import { useThemeStore } from '@/src/shared/store/themeStore';
import { isLightTheme } from '@/src/shared/theme';

export function AppToaster() {
  const theme = useThemeStore((state) => state.theme);

  return (
    <Toaster
      theme={isLightTheme(theme) ? 'light' : 'dark'}
      position="top-right"
      toastOptions={{
        className: 'font-sans text-sm',
        duration: 4000,
      }}
    />
  );
}
