'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuthStore } from '@/lib/store';
import { useFleetEvents } from '@/lib/hooks/useFleetEvents';
import { api } from '@/lib/api';
import {
  Monitor,
  Wifi,
  Code2,
  LayoutDashboard,
  LogOut,
  BarChart3,
  Users,
  ListTodo,
  FolderOpen,
  ScrollText,
  Radar,
  Webhook,
  Settings,
} from 'lucide-react';
import { Button } from '@/components/ui/button';

const NAV_ITEMS = [
  { href: '/dashboard', label: 'Dashboard', icon: BarChart3 },
  { href: '/devices', label: 'Devices', icon: LayoutDashboard },
  { href: '/groups', label: 'Groups', icon: FolderOpen },
  { href: '/stream', label: 'Remote View', icon: Monitor },
  { href: '/tasks', label: 'Tasks', icon: ListTodo },
  { href: '/scripts', label: 'Scripts', icon: Code2 },
  { href: '/vpn', label: 'VPN', icon: Wifi },
  { href: '/discovery', label: 'Discovery', icon: Radar },
  { href: '/users', label: 'Users', icon: Users },
  { href: '/audit', label: 'Audit Log', icon: ScrollText },
  { href: '/webhooks', label: 'Webhooks', icon: Webhook },
  { href: '/settings', label: 'Settings', icon: Settings },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { logout } = useAuthStore();

  // Real-time fleet events — auto-invalidates queries on device/task/vpn changes
  useFleetEvents();

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout', {}, { withCredentials: true });
    } catch {
      // ignore errors — logout anyway
    }
    logout();
    router.push('/login');
  };

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <aside className="w-56 border-r border-border flex flex-col">
        <div className="p-4 border-b border-border">
          <h1 className="font-bold text-lg text-primary">Sphere</h1>
          <p className="text-xs text-muted-foreground">Platform</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                pathname.startsWith(href)
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent'
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </Link>
          ))}
        </nav>
        <div className="p-3 border-t border-border">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start gap-2 text-muted-foreground"
            onClick={handleLogout}
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </Button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  );
}
