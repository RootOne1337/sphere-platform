import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Code2 } from 'lucide-react';

export function LuaNode({ data, selected }: NodeProps) {
  const d = data as { code?: string };
  const preview = (d.code ?? '').split('\n')[0].slice(0, 30);
  return (
    <div
      className={`rounded-lg border-2 p-3 bg-yellow-950 min-w-36 text-center ${
        selected ? 'border-yellow-400' : 'border-yellow-700'
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2 justify-center mb-1">
        <Code2 className="w-4 h-4 text-yellow-400" />
        <span className="text-sm font-medium text-yellow-200">Lua</span>
      </div>
      <p className="text-xs text-yellow-600 font-mono truncate">{preview || '…'}</p>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
