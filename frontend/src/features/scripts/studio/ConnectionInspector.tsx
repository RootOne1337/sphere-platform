'use client';
import type { Connection, Edge, Node } from '@xyflow/react';
import { Unplug, GitBranch } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { connectionOutlets, OUTLET_LABELS } from '@/lib/dag/connections';
import { actionLabel } from './presentation';

export function ConnectionInspector({ edge, nodes, writable, reconnect, remove }: {
  edge: Edge; nodes: Node[]; writable: boolean; reconnect: (connection: Connection) => void; remove: () => void;
}) {
  const source = nodes.find(node => node.id === edge.source);
  const outlet = edge.sourceHandle ?? null;
  const outlets = source ? connectionOutlets(source) : [];
  if (!outlets.includes(outlet)) outlets.unshift(outlet);
  const change = (patch: Partial<Connection>) => reconnect({ source: edge.source, target: edge.target, sourceHandle: outlet, targetHandle: null, ...patch });
  const label = (node: Node) => `${actionLabel(String((node.data.action as { type?: string })?.type))} · ${node.id}`;
  const selectClass = 'h-9 w-full min-w-0 rounded-lg border bg-background px-2 text-xs disabled:opacity-50';
  return <section aria-label="Редактор связи" className="space-y-4">
    <div><h2 className="flex items-center gap-2 text-sm font-semibold"><GitBranch className="size-4 text-primary" />Связь между шагами</h2><p className="mt-2 text-xs leading-5 text-muted-foreground">Выберите другой шаг или выход. Изменение сразу применяется к графу и исходнику.</p></div>
    <label className="block space-y-2 text-xs font-medium">Откуда<select aria-label="Источник связи" className={selectClass} value={edge.source} disabled={!writable} onChange={event => {
      const next = nodes.find(node => node.id === event.target.value);
      if (next) { const available = connectionOutlets(next); change({ source: next.id, sourceHandle: available.includes(outlet) ? outlet : available[0] ?? null }); }
    }}>{nodes.filter(node => connectionOutlets(node).length > 0).map(node => <option key={node.id} value={node.id}>{label(node)}</option>)}</select></label>
    <label className="block space-y-2 text-xs font-medium">Когда<select aria-label="Выход связи" className={selectClass} value={outlet ?? 'next'} disabled={!writable} onChange={event => change({ sourceHandle: event.target.value === 'next' ? null : event.target.value })}>{outlets.map(handle => <option key={handle ?? 'next'} value={handle ?? 'next'}>{OUTLET_LABELS[handle ?? 'next']}</option>)}</select></label>
    <label className="block space-y-2 text-xs font-medium">Куда<select aria-label="Цель связи" className={selectClass} value={edge.target} disabled={!writable} onChange={event => change({ target: event.target.value })}>{nodes.filter(node => (node.data.action as { type?: string })?.type !== 'start').map(node => <option key={node.id} value={node.id}>{label(node)}</option>)}</select></label>
    <Button variant="outline" className="w-full border-destructive/30 text-destructive" disabled={!writable} onClick={remove}><Unplug className="mr-2 size-4" />Разорвать связь</Button>
    <p className="rounded-lg border bg-muted/20 p-3 text-[11px] leading-5 text-muted-foreground">Шаги сохранятся. Разорванный маршрут нужно собрать заново перед публикацией. Delete / Backspace удаляет выбранную связь; «Отменить изменение» восстанавливает исходник.</p>
    <dl className="text-[10px] text-muted-foreground"><dt>ID связи</dt><dd className="mt-1 break-all font-mono">{edge.id}</dd></dl>
  </section>;
}
