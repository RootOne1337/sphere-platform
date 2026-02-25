import { Handle, Position, type NodeProps } from '@xyflow/react';
import { GitBranch } from 'lucide-react';

export function ConditionNode({ data, selected }: NodeProps) {
  const d = data as { condition_expr?: string };
  return (
    <div
      className={`rounded-lg border-2 p-3 bg-orange-950 min-w-36 text-center ${
        selected ? 'border-orange-400' : 'border-orange-700'
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2 justify-center mb-1">
        <GitBranch className="w-4 h-4 text-orange-400" />
        <span className="text-sm font-medium text-orange-200">Condition</span>
      </div>
      <p className="text-xs text-orange-500 font-mono truncate">
        {d.condition_expr ?? 'true'}
      </p>
      {/* true_branch */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="true_branch"
        style={{ left: '30%' }}
      />
      {/* false_branch */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="false_branch"
        style={{ left: '70%' }}
      />
      <div className="flex justify-between text-xs text-gray-600 mt-2 px-1">
        <span>true</span>
        <span>false</span>
      </div>
    </div>
  );
}
