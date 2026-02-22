import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Square } from 'lucide-react';

export function EndNode({ selected }: NodeProps) {
  return (
    <div
      className={`rounded-full border-2 p-3 bg-red-950 w-16 h-16 flex flex-col items-center justify-center ${
        selected ? 'border-red-400' : 'border-red-700'
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <Square className="w-5 h-5 text-red-400 fill-red-400" />
      <span className="text-xs text-red-300 mt-0.5">End</span>
    </div>
  );
}
