'use client';
import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Play, Square, GitBranch, Clock3, MousePointer2, ScanSearch, Code2, Smartphone, CheckCheck } from 'lucide-react';
import { actionLabel, actionSummary } from '@/src/features/scripts/studio/presentation';
import type { DagNodeData } from '@/lib/dag/nodeTypes';

export const WorkflowNode = memo(function WorkflowNode({ data, selected }: NodeProps) {
  const d = data as DagNodeData;
  const type = d.action.type;
  const branch = type === 'condition';
  const Icon = type === 'start' ? Play : type === 'end' ? Square : branch ? GitBranch : type === 'sleep' ? Clock3
    : type.includes('element') || type === 'assert' ? ScanSearch : type === 'tap' || type === 'swipe' ? MousePointer2
    : type === 'lua' || type === 'shell' || type.includes('variable') ? Code2 : Smartphone;
  const color = type === 'start' ? 'text-emerald-600 dark:text-emerald-400' : type === 'end' ? 'text-slate-500'
    : branch ? 'text-amber-600 dark:text-amber-400' : 'text-primary';
  return <div className={`studio-workflow-node ${selected ? 'is-selected' : ''} ${d.execution ? `is-${d.execution}` : ''}`}>
    {type !== 'start' && <Handle type="target" position={Position.Left} title="Вход в шаг" className="!size-3 !border-2 !border-background !bg-muted-foreground" />}
    <div className="flex items-center gap-3 border-b border-border/70 px-3 py-3">
      <span className={`flex size-9 shrink-0 items-center justify-center rounded-xl bg-muted ${color}`}><Icon className="size-4" /></span>
      <div className="min-w-0 flex-1"><p className="truncate text-[13px] font-semibold">{actionLabel(type)}</p><p className="mt-0.5 font-mono text-[10px] text-muted-foreground">{type}</p></div>
      {d.execution === 'success' && <CheckCheck className="size-4 text-emerald-500" />}
    </div>
    <div className="px-3 py-2"><p title={actionSummary(d.action)} className="truncate text-[11px] text-muted-foreground">{actionSummary(d.action)}</p>
      <div className="mt-2 flex items-center justify-between gap-2 text-[9px] text-muted-foreground"><span>{(d.timeout_ms ?? 30000) / 1000} с · retry {d.retry ?? 0}</span><span>{branch ? 'Да / Нет / Ошибка' : type === 'end' ? 'Конец' : 'Успех / Ошибка'}</span></div>
    </div>
    {type !== 'end' && <>
      {branch ? <><Handle type="source" id="true_branch" position={Position.Right} style={{ top: '27%' }} title="Да: on_true" className="!size-3 !bg-emerald-500" /><Handle type="source" id="false_branch" position={Position.Right} style={{ top: '53%' }} title="Нет: on_false" className="!size-3 !bg-amber-500" /></>
        : <Handle type="source" position={Position.Right} style={{ top: '35%' }} title="Успех: on_success" className="!size-3 !bg-primary" />}
      <Handle type="source" id="failure" position={Position.Right} style={{ top: '80%' }} title="Ошибка: on_failure" className="!size-3 !bg-rose-500" />
    </>}
  </div>;
});
