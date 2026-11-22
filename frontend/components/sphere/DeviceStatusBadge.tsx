import { Badge } from '@/components/ui/badge';
import { Activity, HelpCircle, LoaderCircle, Wifi, WifiOff } from 'lucide-react';

export function DeviceStatusBadge({ status }: { status: string }) {
  const variants = {
    online: {
      variant: 'outline' as const,
      icon: Wifi,
      label: 'В сети',
      className: 'border-success/30 bg-success/10 text-success',
    },
    offline: {
      variant: 'secondary' as const,
      icon: WifiOff,
      label: 'Не в сети',
      className: 'border-border bg-muted text-muted-foreground',
    },
    connecting: {
      variant: 'outline' as const,
      icon: LoaderCircle,
      label: 'Подключение',
      className: 'border-warning/30 bg-warning/10 text-warning',
    },
    busy: {
      variant: 'outline' as const,
      icon: Activity,
      label: 'В работе',
      className: 'border-warning/30 bg-warning/10 text-warning',
    },
    maintenance: {
      variant: 'outline' as const,
      icon: Activity,
      label: 'Обслуживание',
      className: 'border-primary/60 text-primary',
    },
    error: {
      variant: 'destructive' as const,
      icon: HelpCircle,
      label: 'Ошибка',
      className: '',
    },
    unknown: {
      variant: 'outline' as const,
      icon: HelpCircle,
      label: 'Неизвестно',
      className: '',
    },
  };

  const cfg = variants[status as keyof typeof variants] ?? variants.unknown;
  const Icon = cfg.icon;

  return (
    <Badge variant={cfg.variant} className={`self-start gap-1 ${cfg.className}`}>
      <Icon className={`w-3 h-3 ${status === 'connecting' ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
      {cfg.label}
    </Badge>
  );
}
