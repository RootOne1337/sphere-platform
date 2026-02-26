'use client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useInitAuth, useAuthStore } from '@/lib/store';

// Публичные пути — не требуют авторизации
const PUBLIC_PATHS = ['/login'];

// ⚠️ АВТОРИЗАЦИЯ ОТКЛЮЧЕНА НА ВРЕМЯ РАЗРАБОТКИ
// TODO: вернуть обратно: const DEV_SKIP_AUTH = process.env.NEXT_PUBLIC_DEV_SKIP_AUTH === 'true';
const DEV_SKIP_AUTH = true;

/**
 * Client-side auth guard.
 * Заменяет middleware redirect — работает стабильно через tunnel (Serveo/Cloudflare),
 * не кэшируется в Next.js Router Cache.
 */
function AuthInitializer({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const ready = useInitAuth();
  const accessToken = useAuthStore((s) => s.accessToken);

  useEffect(() => {
    // DEV_SKIP_AUTH: полностью пропускаем auth guard
    if (DEV_SKIP_AUTH) return;
    if (!ready) return;
    const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));
    if (!isPublic && !accessToken) {
      // Не авторизован на защищённой странице → login
      router.replace('/login');
    } else if (isPublic && accessToken) {
      // Уже залогинен на login странице → dashboard
      router.replace('/dashboard');
    }
  }, [ready, accessToken, pathname, router]);

  if (DEV_SKIP_AUTH) return <>{children}</>;

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950">
        <div className="text-muted-foreground text-sm">Loading…</div>
      </div>
    );
  }
  return <>{children}</>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  }));

  return (
    <QueryClientProvider client={queryClient}>
      <AuthInitializer>{children}</AuthInitializer>
    </QueryClientProvider>
  );
}
