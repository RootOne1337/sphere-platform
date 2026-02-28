'use client';

import { useState, useEffect } from 'react';
import { useAuthStore } from '@/lib/store';
import { useFleetEvents } from '@/lib/hooks/useFleetEvents';
import { NOCSidebar } from '@/src/features/navigation/NOCSidebar';
import { ContextInspector } from '@/src/features/inspector/ContextInspector';
import { GlobalCommandPalette } from '@/src/features/navigation/GlobalCommandPalette';
import { AppearanceDrawer } from '@/src/features/preferences/AppearanceDrawer';
import { useUIStore } from '@/src/shared/store/useUIStore';
import { Menu } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  // Real-time fleet events — auto-invalidates queries on device/task/vpn changes
  useFleetEvents();

  const [isAppearanceOpen, setIsAppearanceOpen] = useState(false);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const { fontSize, accentColor, density } = useUIStore();

  // CSS Variable Injection for Real-time Theming
  useEffect(() => {
    const root = document.documentElement;

    // 1. Dymamic Font Scaling (rem scaling)
    switch (fontSize) {
      case 'sm': root.style.fontSize = '14px'; break;
      case 'base': root.style.fontSize = '16px'; break;
      case 'lg': root.style.fontSize = '18px'; break;
    }

    // 2. Dynamic Accent Colors (Tailwind HSL overrides)
    // Default is violet, others override root variables mapped to bg-primary, text-primary etc.
    switch (accentColor) {
      case 'violet': root.style.setProperty('--primary', '262.1 83.3% 57.8%'); break;
      case 'blue': root.style.setProperty('--primary', '221.2 83.2% 53.3%'); break;
      case 'emerald': root.style.setProperty('--primary', '152.4 76% 41.5%'); break;
      case 'rose': root.style.setProperty('--primary', '346.8 77.2% 49.8%'); break;
      case 'amber': root.style.setProperty('--primary', '38 92% 50%'); break;
    }

    // 3. Density Classes (will be picked up by deep UI components optionally)
    if (density === 'compact') root.classList.add('density-compact');
    else root.classList.remove('density-compact');

  }, [fontSize, accentColor, density]);

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      {/* Схлопывающийся NOC Сайдбар */}
      <NOCSidebar
        onOpenAppearance={() => setIsAppearanceOpen(true)}
        isMobileOpen={isMobileSidebarOpen}
        onMobileClose={() => setIsMobileSidebarOpen(false)}
      />

      {/* Основная рабочая область (Multi-Pane Layout Ready) */}
      <main className="flex-1 overflow-auto flex flex-col relative bg-background">

        {/* Мобильная шапка (только на маленьких экранах) */}
        <div className="lg:hidden flex items-center justify-between h-14 px-4 bg-card border-b border-border shrink-0">
          <div className="flex items-center gap-2 text-primary font-mono font-bold tracking-wider">
            <div className="w-6 h-6 bg-primary rounded-sm text-primary-foreground flex items-center justify-center">S</div>
            SPHERE<span className="text-muted-foreground font-normal text-xs">NOC</span>
          </div>
          <Button variant="ghost" size="icon" onClick={() => setIsMobileSidebarOpen(true)}>
            <Menu className="w-5 h-5 text-foreground" />
          </Button>
        </div>

        {children}

        {/* Глобальная панель настроек внешнего вида (Themes, Scaling) */}
        <AppearanceDrawer open={isAppearanceOpen} onClose={() => setIsAppearanceOpen(false)} />

        {/* Глобальный Инспектор Контекста */}
        <ContextInspector />

        {/* Глобальная Командная Панель (Ctrl+K) */}
        <GlobalCommandPalette />
      </main>
    </div>
  );
}
