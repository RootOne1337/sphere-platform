import { Play } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';

export interface PipelineRecoveryState {
  execution_phase?: string;
  execution_lease_until?: string | null;
  cancel_requested_at?: string | null;
}

export function PipelineResumeControl({ run, onResume, pending = false }: {
  run: PipelineRecoveryState;
  onResume: () => void;
  pending?: boolean;
}) {
  const reason = run.cancel_requested_at
    ? 'Ожидается подтверждение отмены'
    : run.execution_phase === 'unknown'
      ? 'Результат шага неизвестен — требуется проверка'
      : run.execution_lease_until
        ? 'Ожидается завершение шага или восстановление исполнителя'
        : null;

  return (
    <div className="flex items-center gap-2">
      {reason && <span role="status" className="max-w-64 whitespace-normal text-[10px] text-warning">{reason}</span>}
      <Button variant="ghost" size="tiny" disabled={!!reason || pending}
        className="text-muted-foreground hover:text-success hover:bg-success/10"
        onClick={onResume} title={reason || 'Возобновить'} aria-label="Возобновить pipeline">
        <Play className="w-3 h-3" />
      </Button>
    </div>
  );
}
