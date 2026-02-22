import { Handle, Position, type NodeProps } from '@xyflow/react';
import { MoveHorizontal } from 'lucide-react';

export function SwipeNode({ data, selected }: NodeProps) {
  const d = data as { x1?: number; y1?: number; x2?: number; y2?: number; duration_ms?: number };
  return (
    <div
      className={`rounded-lg border-2 p-3 bg-purple-950 min-w-32 text-center ${
        selected ? 'border-purple-400' : 'border-purple-700'
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2 justify-center mb-1">
        <MoveHorizontal className="w-4 h-4 text-purple-400" />
        <span className="text-sm font-medium text-purple-200">Swipe</span>
      </div>
      <p className="text-xs text-purple-400">
        ({d.x1 ?? 0},{d.y1 ?? 0}) → ({d.x2 ?? 0},{d.y2 ?? 0})
      </p>
      {d.duration_ms != null && (
        <p className="text-xs text-gray-500 mt-1">{d.duration_ms}ms</p>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
