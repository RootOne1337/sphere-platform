'use client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useInitAuth, useAuthStore } from '@/lib/store';
import { Button } from '@/src/shared/ui/button';
import { AccountAppearanceSync } from '@/src/features/preferences/AccountAppearanceSync';
import { CapabilitiesProvider, useCapabilities } from '@/src/features/access/Capabilities';
import { clearReturnDestination, readReturnDestination, rememberReturnDestination } from '@/src/features/access/returnDestination';

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
  const initialization = useInitAuth();
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const sessionVersion = useAuthStore((s) => s.sessionVersion);
  const manualLogoutVersion = useAuthStore((s) => s.manualLogoutVersion);
  const isPublic = PUBLIC_PATHS.includes(pathname);
  const authenticated = Boolean(accessToken && user);
  const ready = initialization.state === 'ready';

  useEffect(() => {
    if (isPublic && manualLogoutVersion !== null) useAuthStore.setState({ manualLogoutVersion: null });
    if (!ready || isPublic || authenticated) return;
    if (manualLogoutVersion !== sessionVersion) {
      const location = window.location;
      rememberReturnDestination(pathname + (location.pathname === pathname ? location.search : ''));
    }
    router.replace('/login');
  }, [ready, authenticated, isPublic, pathname, router, manualLogoutVersion, sessionVersion]);

  if (!isPublic && !authenticated && initialization.state === 'unavailable') {
    return <AuthStatus title="Не удалось проверить сессию" detail="Сервис входа временно недоступен. Повторите проверку на этой странице." action={{ label: 'Повторить проверку', perform: initialization.retry }} />;
  }

  // A redirect is asynchronous. Keep private hooks/streams unmounted until allowed.
  if ((!ready && initialization.state !== 'unavailable') || (!isPublic && !authenticated)) return <AuthStatus title="Проверяем сессию…" />;
  const identity = authenticated ? JSON.stringify([sessionVersion, user!.org_id, user!.id, user!.role]) : 'anonymous';
  return <SessionQueries key={identity}>
    {isPublic && authenticated ? <CapabilitiesProvider><LoginDestination /></CapabilitiesProvider>
      : authenticated ? <AccountAppearanceSync>{children}</AccountAppearanceSync> : children}
  </SessionQueries>;
}

function AuthStatus({ title, detail, action }: { title: string; detail?: string; action?: { label: string; perform: () => void } }) {
  return <main className="flex min-h-dvh items-center justify-center bg-background p-4 text-foreground">
    <div className="w-full max-w-md space-y-3 rounded-xl border bg-card p-6">
      <h1 className="font-semibold" role={action ? 'alert' : 'status'}>{title}</h1>
      {detail && <p className="text-sm text-muted-foreground">{detail}</p>}
      {action && <Button variant="outline" onClick={action.perform}>{action.label}</Button>}
    </div>
  </main>;
}

function LoginDestination() {
  const router = useRouter();
  const access = useCapabilities();
  const [target] = useState(readReturnDestination);
  const fallback = access.canAccessRoute('/dashboard') ? '/dashboard' : '/settings';
  const denied = Boolean(target && !access.canAccessRoute(target));
  useEffect(() => {
    if (!access.verified || denied) return;
    clearReturnDestination();
    router.replace(target ?? fallback);
  }, [access.verified, denied, fallback, router, target]);
  if (access.failed) return <AuthStatus title="Не удалось подтвердить права" detail="Вход выполнен. Для перехода нужно проверить доступные разделы." action={{ label: 'Повторить проверку', perform: access.retry }} />;
  if (access.verified && denied) return <AuthStatus title="Запрошенный раздел недоступен" detail="Для этой учётной записи выбрана доступная начальная страница." action={{ label: 'Открыть доступный раздел', perform: () => {
    clearReturnDestination();
    router.replace(fallback);
  } }} />;
  return <AuthStatus title="Проверяем права…" />;
}

function SessionQueries({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        retry: 0,
        // Reconcile reads after a suspended tab returns; mutations are not replayed.
        refetchOnWindowFocus: true,
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
