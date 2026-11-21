import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Camera } from 'lucide-react';
import { ActionRoutes } from './ActionRoutes';

export function ScreenshotNode({ data, selected }: NodeProps) {
  const d = data.action as { save_to?: string };
  return (
    <div
      className={`rounded-lg border-2 p-3 bg-teal-950 min-w-28 text-center ${
        selected ? 'border-teal-400' : 'border-teal-700'
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2 justify-center mb-1">
        <Camera className="w-4 h-4 text-teal-400" />
        <span className="text-sm font-medium text-teal-200">Screenshot</span>
      </div>
      <p className="text-xs text-teal-500">
        {d.save_to ? `→ ${d.save_to}` : 'Результат шага'}
      </p>
      <ActionRoutes />
    </div>
  );
}
