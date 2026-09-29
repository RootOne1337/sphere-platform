'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { ChevronRight, Menu, Moon, Search, Sun } from 'lucide-react';
import { useFleetEvents } from '@/lib/hooks/useFleetEvents';
import { NOCSidebar } from '@/src/features/navigation/NOCSidebar';
import { ContextInspector } from '@/src/features/inspector/ContextInspector';
import { GlobalCommandPalette } from '@/src/features/navigation/GlobalCommandPalette';
import { AppearanceDrawer } from '@/src/features/preferences/AppearanceDrawer';
import { useCommandPaletteStore } from '@/src/features/navigation/commandPaletteStore';
import { useUIStore } from '@/src/shared/store/useUIStore';
import { useThemeStore } from '@/src/shared/store/themeStore';
import { Button } from '@/src/shared/ui/button';
import { BuildProvenance } from '@/src/shared/ui/BuildProvenance';

const ROUTE_TITLES: Record<string, string> = {
  '/dashboard': 'Обзор парка',
  '/monitoring': 'Инфраструктура',
  '/devices': 'Реестр устройств',
  '/stream': 'Видеопоток',
  '/discovery': 'Обнаружение устройств',
  '/groups': 'Группы',
  '/locations': 'Локации',
  '/tasks': 'Задания',
  '/orchestration': 'Оркестрация',
  '/pipeline-settings': 'Пайплайны',
  '/accounts': 'Игровые аккаунты',
  '/scripts': 'Скрипты',
  '/events': 'События устройств',
  '/event-triggers': 'Триггеры событий',
  '/sessions': 'Сессии',
  '/vpn': 'Туннели и VPN',
  '/webhooks': 'Вебхуки',
  '/users': 'Пользователи',
  '/audit': 'Журнал аудита',
  '/logs': 'Системные логи',
  '/updates': 'Обновления',
  '/settings': 'Конфигурация',
};

function currentRouteTitle(pathname: string) {
  const route = Object.keys(ROUTE_TITLES)
    .sort((left, right) => right.length - left.length)
    .find((candidate) => pathname === candidate || pathname.startsWith(`${candidate}/`));
  return route ? ROUTE_TITLES[route] : 'Рабочая область';
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  useFleetEvents();

  const pathname = usePathname();
  const [isAppearanceOpen, setIsAppearanceOpen] = useState(false);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const { fontSize, accentColor, density, setTheme: setUiTheme } = useUIStore();
  const theme = useThemeStore((state) => state.theme);
  const setTheme = useThemeStore((state) => state.setTheme);
  const toggleCommandPalette = useCommandPaletteStore((state) => state.toggle);
  const isLight = theme === 'light-corporate';

  useEffect(() => {
    const root = document.documentElement;

    switch (fontSize) {
      case 'sm': root.style.fontSize = '14px'; break;
      case 'base': root.style.fontSize = '16px'; break;
      case 'lg': root.style.fontSize = '18px'; break;
    }

    switch (accentColor) {
      case 'violet': root.style.setProperty('--primary', '262.1 83.3% 57.8%'); break;
      case 'blue': root.style.setProperty('--primary', '221.2 83.2% 53.3%'); break;
      case 'emerald': root.style.setProperty('--primary', '160 74% 34%'); break;
      case 'rose': root.style.setProperty('--primary', '346.8 77.2% 42%'); break;
      case 'amber': root.style.setProperty('--primary', '38 92% 40%'); break;
    }

    root.classList.toggle('density-compact', density === 'compact');
  }, [fontSize, accentColor, density]);

  const toggleTheme = () => {
    const nextTheme = isLight ? 'neo-dark' : 'light-corporate';
    setTheme(nextTheme);
    setUiTheme(isLight ? 'dark' : 'light');
  };

  return (
    <div className="relative flex h-dvh min-h-0 overflow-hidden bg-background text-foreground">
      <a href="#main-content" className="sr-only z-[200] rounded-md bg-card p-3 text-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:ring-2 focus:ring-ring">
        Перейти к содержимому
      </a>

      <NOCSidebar
        onOpenAppearance={() => setIsAppearanceOpen(true)}
        isMobileOpen={isMobileSidebarOpen}
        onMobileClose={() => setIsMobileSidebarOpen(false)}
      />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="z-30 flex h-16 shrink-0 items-center justify-between gap-4 border-b border-border bg-card/95 px-4 backdrop-blur sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Открыть меню навигации"
              className="h-10 w-10 shrink-0 lg:hidden"
              onClick={() => setIsMobileSidebarOpen(true)}
            >
              <Menu className="h-5 w-5" aria-hidden="true" />
            </Button>
            <nav aria-label="Хлебные крошки" className="flex min-w-0 items-center gap-2 text-sm">
              <Link href="/dashboard" className="hidden shrink-0 text-muted-foreground transition-colors hover:text-foreground sm:inline">Sphere</Link>
              <ChevronRight className="hidden h-4 w-4 shrink-0 text-muted-foreground/60 sm:block" aria-hidden="true" />
              <span aria-current="page" className="truncate font-medium text-foreground">{currentRouteTitle(pathname)}</span>
            </nav>
          </div>

          <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
            <BuildProvenance />
            <Button
              type="button"
              variant="outline"
              className="h-9 gap-2 px-2.5 text-muted-foreground sm:px-3"
              onClick={toggleCommandPalette}
              aria-label="Поиск по разделам и командам"
            >
              <Search className="h-4 w-4" aria-hidden="true" />
              <span className="hidden text-xs sm:inline">Поиск</span>
              <kbd className="hidden rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground md:inline">Ctrl K</kbd>
            </Button>
            <span className="mx-1 hidden h-6 w-px bg-border sm:block" aria-hidden="true" />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9 rounded-lg"
              onClick={toggleTheme}
              aria-label={isLight ? 'Включить тёмную тему' : 'Включить светлую тему'}
              title={isLight ? 'Тёмная тема' : 'Светлая тема'}
            >
              {isLight ? <Moon className="h-[18px] w-[18px]" aria-hidden="true" /> : <Sun className="h-[18px] w-[18px]" aria-hidden="true" />}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9 rounded-lg"
              onClick={() => setIsAppearanceOpen(true)}
              aria-label="Открыть настройки интерфейса"
              title="Настройки интерфейса"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">S</span>
            </Button>
          </div>
        </header>

        <main id="main-content" tabIndex={-1} className="custom-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain bg-background focus:outline-none">
          <div key={pathname} className="workspace-route-enter min-h-full">
            {children}
          </div>
        </main>
      </div>

      <AppearanceDrawer open={isAppearanceOpen} onClose={() => setIsAppearanceOpen(false)} />
      <ContextInspector />
      <GlobalCommandPalette />
    </div>
  );
}
