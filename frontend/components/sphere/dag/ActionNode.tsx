import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Workflow } from 'lucide-react';
import { ActionRoutes } from './ActionRoutes';

export function ActionNode({ data, selected }: NodeProps) {
  const action = data.action as Record<string, unknown>;
  return <div className={`min-w-36 rounded-lg border-2 bg-card p-3 ${selected ? 'border-primary' : 'border-border'}`}>
    <Handle type="target" position={Position.Top} />
    <div className="flex items-center gap-2 text-sm font-medium"><Workflow className="h-4 w-4" />{String(action.type)}</div>
    <p className="mt-1 text-xs text-muted-foreground">Все параметры сохранены</p>
    <ActionRoutes />
  </div>;
}
