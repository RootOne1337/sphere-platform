'use client';

import { Toaster } from 'sonner';
import { useThemeStore } from '@/src/shared/store/themeStore';

export function AppToaster() {
  const theme = useThemeStore((state) => state.theme);

  return (
    <Toaster
      theme={theme === 'light-corporate' ? 'light' : 'dark'}
      position="top-right"
      toastOptions={{
        className: 'font-sans text-sm',
        duration: 4000,
      }}
    />
  );
}
