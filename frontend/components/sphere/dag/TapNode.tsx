import { Handle, Position, type NodeProps } from '@xyflow/react';
import { MousePointerClick } from 'lucide-react';

export function TapNode({ data, selected }: NodeProps) {
  const d = data as { x?: number; y?: number; description?: string };
  return (
    <div
      className={`rounded-lg border-2 p-3 bg-blue-950 min-w-32 text-center ${
        selected ? 'border-blue-400' : 'border-blue-700'
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2 justify-center mb-1">
        <MousePointerClick className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-medium text-blue-200">Tap</span>
      </div>
      <p className="text-xs text-blue-400">
        ({d.x ?? 0}, {d.y ?? 0})
      </p>
      {d.description && (
        <p className="text-xs text-gray-500 mt-1 truncate">{d.description}</p>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
