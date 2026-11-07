import { Radio, RefreshCw, WifiOff } from 'lucide-react';
import type { FleetConnectionState } from '@/lib/hooks/useFleetEvents';

const DESCRIPTIONS: Record<FleetConnectionState, { label: string; detail: string }> = {
  connecting: { label: 'События: подключение', detail: 'Ждём подтверждения от API. Открытый WebSocket ещё не доказывает авторизацию.' },
  live: { label: 'События: подключены', detail: 'API отвечает. Изменения обновляют открытые данные; пропущенное после обрыва сверяется через REST. Это не статус Android или видео.' },
  reconnecting: { label: 'События: восстановление', detail: 'Канал событий потерян; повторяем подключение с задержкой. Периодические чтения API продолжаются.' },
  offline: { label: 'Браузер без сети', detail: 'Браузер сообщает об отсутствии сети. Восстановим канал при её появлении; статус устройств этим не определяется.' },
  unauthorized: { label: 'События: нет доступа', detail: 'API отклонил авторизацию. Не повторяем старый токен; канал возобновится после обновления сессии Sphere.' },
};

export function FleetConnectionStatus({ state }: { state: FleetConnectionState }) {
  const description = DESCRIPTIONS[state];
  const Icon = state === 'live' ? Radio : state === 'connecting' || state === 'reconnecting' ? RefreshCw : WifiOff;
  return <span role="status" aria-live="polite" data-fleet-connection={state} title={description.detail}
    className={`flex h-9 shrink-0 items-center gap-1.5 rounded-lg border px-2 text-xs ${state === 'live' ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300' : 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200'}`}>
    <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
    <span className="hidden xl:inline">{description.label}</span>
    <span className="sr-only xl:hidden">{description.label}</span>
  </span>;
}
