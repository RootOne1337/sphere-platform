import { Badge } from '@/components/ui/badge';
import { Wifi, WifiOff, HelpCircle } from 'lucide-react';

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
      <Icon className="w-3 h-3" />
      {cfg.label}
    </Badge>
  );
}
