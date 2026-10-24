import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Clock } from 'lucide-react';
import { ActionRoutes } from './ActionRoutes';

export function SleepNode({ data, selected }: NodeProps) {
  const d = data.action as { ms?: number };
  return (
    <div
      className={`rounded-lg border-2 p-3 bg-gray-800 min-w-28 text-center ${
        selected ? 'border-gray-400' : 'border-gray-600'
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2 justify-center mb-1">
        <Clock className="w-4 h-4 text-gray-400" />
        <span className="text-sm font-medium text-gray-200">Sleep</span>
      </div>
      <p className="text-xs text-gray-400">{d.ms ?? 1000}ms</p>
      <ActionRoutes />
    </div>
  );
}
