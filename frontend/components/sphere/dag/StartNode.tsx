import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Play } from 'lucide-react';

export function StartNode({ selected }: NodeProps) {
  return (
    <div
      className={`rounded-full border-2 p-3 bg-green-950 w-16 h-16 flex flex-col items-center justify-center ${
        selected ? 'border-green-400' : 'border-green-700'
      }`}
    >
      <Play className="w-5 h-5 text-green-400 fill-green-400" />
      <span className="text-xs text-green-300 mt-0.5">Start</span>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
