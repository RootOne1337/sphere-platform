import { Badge } from '@/components/ui/badge';
import { Activity, HelpCircle, LoaderCircle, Wifi, WifiOff } from 'lucide-react';

export function DeviceStatusBadge({ status }: { status: string }) {
  const variants = {
    online: {
      variant: 'default' as const,
      icon: Wifi,
      label: 'Online',
      className: 'bg-green-600',
    },
    offline: {
      variant: 'secondary' as const,
      icon: WifiOff,
      label: 'Offline',
      className: 'bg-gray-600',
    },
    connecting: {
      variant: 'outline' as const,
      icon: LoaderCircle,
      label: 'Connecting',
      className: 'border-amber-500 text-amber-500',
    },
    busy: {
      variant: 'outline' as const,
      icon: Activity,
      label: 'Busy',
      className: 'border-amber-500 text-amber-500',
    },
    maintenance: {
      variant: 'outline' as const,
      icon: Activity,
      label: 'Maintenance',
      className: 'border-primary/60 text-primary',
    },
    error: {
      variant: 'destructive' as const,
      icon: HelpCircle,
      label: 'Error',
      className: '',
    },
    unknown: {
      variant: 'outline' as const,
      icon: HelpCircle,
      label: 'Unknown',
      className: '',
    },
  };

  const cfg = variants[status as keyof typeof variants] ?? variants.unknown;
  const Icon = cfg.icon;

  return (
    <Badge variant={cfg.variant} className={`gap-1 ${cfg.className}`}>
      <Icon className={`w-3 h-3 ${status === 'connecting' ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
      {cfg.label}
    </Badge>
  );
}
