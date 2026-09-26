'use client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useInitAuth, useAuthStore } from '@/lib/store';

// Публичные пути — не требуют авторизации
const PUBLIC_PATHS = ['/login'];

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
  const user = useAuthStore((s) => s.user);
  const sessionVersion = useAuthStore((s) => s.sessionVersion);
  const isPublic = PUBLIC_PATHS.includes(pathname);
  const authenticated = Boolean(accessToken && user);

  useEffect(() => {
    if (!ready) return;
    if (!isPublic && !authenticated) {
      // Не авторизован на защищённой странице → login
      router.replace('/login');
    } else if (isPublic && authenticated) {
      // Уже залогинен на login странице → dashboard
      router.replace('/dashboard');
    }
  }, [ready, authenticated, isPublic, router]);

  // A redirect is asynchronous. Keep private hooks/streams unmounted until allowed.
  if (!ready || isPublic === authenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950">
        <div className="text-muted-foreground text-sm">Loading…</div>
      </div>
    );
  }
  const identity = authenticated ? JSON.stringify([sessionVersion, user!.org_id, user!.id, user!.role]) : 'anonymous';
  return <SessionQueries key={identity}>{children}</SessionQueries>;
}

function SessionQueries({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        retry: 0,
        refetchOnWindowFocus: false,
      },
    },
  }));

  useEffect(() => () => {
    // Retired requests may finish, but their client is no longer visible to another identity.
    void queryClient.cancelQueries();
    queryClient.clear();
  }, [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );
}

export function Providers({ children }: { children: React.ReactNode }) {
  return <AuthInitializer>{children}</AuthInitializer>;
}
