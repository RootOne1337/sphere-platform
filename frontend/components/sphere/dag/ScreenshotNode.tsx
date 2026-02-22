import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Camera } from 'lucide-react';

export function ScreenshotNode({ data, selected }: NodeProps) {
  const d = data as { save_to_results?: boolean };
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
        {d.save_to_results ? 'save to results' : 'discard'}
      </p>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
