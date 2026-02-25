'use client';
import { use, useState, useMemo } from 'react';
import { useTask, useTaskLogs, useCancelTask, useStopTask, useTaskProgress, useCreateTask, useTaskLiveLogs, type NodeExecutionLog, type LiveLogEntry } from '@/lib/hooks/useTasks';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import Link from 'next/link';

interface Props {
  params: Promise<{ id: string }>;
}

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  queued:    { label: 'Queued',    color: 'text-yellow-400', bg: 'bg-yellow-500/20' },
  assigned:  { label: 'Assigned',  color: 'text-blue-400',   bg: 'bg-blue-500/20' },
  running:   { label: 'Running',   color: 'text-cyan-400',   bg: 'bg-cyan-500/20' },
  completed: { label: 'Completed', color: 'text-green-400',  bg: 'bg-green-500/20' },
  failed:    { label: 'Failed',    color: 'text-red-400',    bg: 'bg-red-500/20' },
  cancelled: { label: 'Cancelled', color: 'text-gray-400',   bg: 'bg-gray-500/20' },
};

const ACTION_ICONS: Record<string, string> = {
  start: '🚀', end: '🏁', sleep: '⏳', condition: '🔀', tap: '👆',
  find_element: '🔍', swipe: '👋', input_text: '⌨️', screenshot: '📸',
  launch_app: '📱', back: '◀️', home: '🏠', scroll: '📜',
};

export default function TaskDetailPage({ params }: Props) {
  const { id } = use(params);
  const { data: task, isLoading } = useTask(id);
  const { data: logsFromApi } = useTaskLogs(id);
  const cancelTask = useCancelTask();
  const stopTask = useStopTask();
  const createTask = useCreateTask();
  const [restarting, setRestarting] = useState(false);
  const isActive = task ? ['queued', 'assigned', 'running'].includes(task.status) : false;
  const { data: liveProgress } = useTaskProgress(id, isActive);
  const { data: liveLogs } = useTaskLiveLogs(id, isActive);

  // Fallback: if /logs API fails or returns empty, extract from task.result.node_logs
  const resultNodeLogs = (task?.result as Record<string, unknown> | null)?.node_logs as NodeExecutionLog[] | undefined;
  const logs = (logsFromApi && logsFromApi.length > 0) ? logsFromApi : resultNodeLogs ?? logsFromApi;

  if (isLoading) {
    return (
      <div className="p-6 flex items-center gap-3 text-muted-foreground">
        <div className="h-4 w-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
        Loading task…
      </div>
    );
  }

  if (!task) {
    return <div className="p-6 text-muted-foreground">Task not found</div>;
  }

  const statusCfg = STATUS_CONFIG[task.status] ?? STATUS_CONFIG.queued;
  const result = task.result as Record<string, unknown> | null;

  // Live progress from Redis (when running) or from result (when done)
  const nodesExecuted = liveProgress?.nodes_done ?? (result?.nodes_executed as number) ?? logs?.length ?? 0;
  const totalNodes = liveProgress?.total_nodes ?? (result?.total_nodes as number) ?? (result?.node_logs as unknown[])?.length ?? 0;
  const cycles = liveProgress?.cycles ?? (totalNodes > 0 ? Math.floor(nodesExecuted / totalNodes) : 0);
  const isCyclic = cycles > 0;
  const currentNode = liveProgress?.current_node ?? '';
  const failedNode = result?.failed_node as string | undefined;

  // Elapsed time
  const elapsedMs = liveProgress?.started_at
    ? Date.now() - liveProgress.started_at * 1000
    : task.started_at
      ? Date.now() - new Date(task.started_at).getTime()
      : 0;

  return (
    <div className="p-6 space-y-6 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">Task Detail</h1>
            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold ${statusCfg.bg} ${statusCfg.color}`}>
              {isActive && <span className="relative flex h-2 w-2"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75" /><span className="relative inline-flex rounded-full h-2 w-2 bg-current" /></span>}
              {statusCfg.label}
            </span>
          </div>
          <p className="text-sm text-muted-foreground font-mono mt-1">{task.id}</p>
        </div>
        <div className="flex gap-2">
          {/* STOP — for running tasks */}
          {task.status === 'running' && (
            <Button
              variant="destructive"
              onClick={() => stopTask.mutate(task.id)}
              disabled={stopTask.isPending}
              className="gap-2 shadow-lg shadow-red-500/20 hover:shadow-red-500/40 transition-all"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
              {stopTask.isPending ? 'Stopping…' : 'Stop'}
            </Button>
          )}

          {/* CANCEL — for queued/assigned */}
          {['queued', 'assigned'].includes(task.status) && (
            <Button
              variant="destructive"
              onClick={() => cancelTask.mutate(task.id)}
              disabled={cancelTask.isPending}
              className="gap-2"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              {cancelTask.isPending ? 'Cancelling…' : 'Cancel'}
            </Button>
          )}

          {/* RESTART — for completed/failed/cancelled tasks */}
          {['completed', 'failed', 'cancelled', 'timeout'].includes(task.status) && (
            <Button
              variant="default"
              disabled={restarting}
              className="gap-2 bg-emerald-600 hover:bg-emerald-500 shadow-lg shadow-emerald-500/20 hover:shadow-emerald-500/40 transition-all"
              onClick={async () => {
                setRestarting(true);
                try {
                  await createTask.mutateAsync({
                    script_id: task.script_id,
                    device_id: task.device_id,
                    priority: task.priority,
                  });
                } finally {
                  setRestarting(false);
                }
              }}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              {restarting ? 'Starting…' : 'Restart'}
            </Button>
          )}

          <Button asChild variant="outline">
            <Link href="/tasks">Back to Tasks</Link>
          </Button>
        </div>
      </div>

      {/* ── Live Execution Dashboard (for running tasks) ─────────────── */}
      {task.status === 'running' && (
        <div className="rounded-xl border bg-gradient-to-br from-cyan-950/30 to-blue-950/20 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="h-3 w-3 rounded-full bg-cyan-400 animate-pulse" />
              <span className="text-sm font-semibold text-cyan-300">Live Execution</span>
            </div>
            <span className="text-xs text-muted-foreground font-mono">{formatElapsed(elapsedMs)}</span>
          </div>

          {/* Metrics grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard label="Nodes Executed" value={String(nodesExecuted)} accent="cyan" />
            <MetricCard label="Cycles" value={String(cycles)} accent="blue" />
            <MetricCard label="Total Nodes" value={String(totalNodes)} accent="gray" />
            <MetricCard label="Elapsed" value={formatElapsed(elapsedMs)} accent="yellow" />
          </div>

          {/* Current node indicator */}
          {currentNode && (
            <div className="flex items-center gap-2 bg-black/30 rounded-lg px-4 py-2.5">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-cyan-400"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <span className="text-xs text-muted-foreground">Current Node:</span>
              <span className="text-sm font-mono font-medium text-cyan-300">{currentNode}</span>
            </div>
          )}

          {/* Indeterminate progress bar for cyclic DAGs */}
          <div className="h-1.5 rounded-full bg-black/30 overflow-hidden">
            <div className="h-full rounded-full bg-gradient-to-r from-cyan-500 via-blue-500 to-cyan-500 animate-indeterminate" style={{ width: '40%' }} />
          </div>
        </div>
      )}

      {/* Progress summary (visible when completed with results) */}
      {task.status !== 'running' && totalNodes > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Execution Summary</span>
            <span className="font-mono font-medium">
              {nodesExecuted} nodes in {cycles > 0 ? `${cycles} cycles` : '1 pass'}
            </span>
          </div>
          {failedNode && (
            <p className="text-xs text-red-400">Failed at node: <span className="font-mono">{failedNode}</span></p>
          )}
        </div>
      )}

      {/* Info grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <InfoCard label="Priority" value={String(task.priority)} />
        <InfoCard label="Device" value={task.device_id.slice(0, 12) + '…'} mono />
        <InfoCard label="Script" value={task.script_id.slice(0, 12) + '…'} mono />
        <InfoCard label="Created" value={new Date(task.created_at).toLocaleString()} />
        <InfoCard label="Started" value={task.started_at ? new Date(task.started_at).toLocaleString() : '—'} />
        <InfoCard label="Finished" value={task.finished_at ? new Date(task.finished_at).toLocaleString() : '—'} />
        <InfoCard label="Duration" value={getDuration(task.started_at, task.finished_at)} />
        <InfoCard label="Batch" value={task.batch_id?.slice(0, 12) ?? '—'} mono />
      </div>

      {/* Error */}
      {task.error_message && (
        <div className="rounded-lg border border-red-800 bg-red-950/50 p-4">
          <p className="text-sm font-medium text-red-400">Error</p>
          <pre className="text-xs text-red-300 mt-1 whitespace-pre-wrap">{task.error_message}</pre>
        </div>
      )}

      {/* ── Live Node Activity (running tasks) ────────────────────────── */}
      {isActive && liveLogs && liveLogs.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold">Live Activity</h2>
            <span className="text-xs text-muted-foreground">{liveLogs.length} events</span>
          </div>
          <LiveLogTimeline entries={liveLogs} />
        </div>
      )}

      {/* ── Execution Logs (completed tasks) ──────────────────────────── */}
      {!isActive && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold">Execution Logs</h2>
            {logs && logs.length > 0 && (
              <span className="text-xs text-muted-foreground">{logs.length} nodes</span>
            )}
          </div>
          {!logs || logs.length === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <p className="text-sm text-muted-foreground">No execution logs available</p>
            </div>
          ) : (
            <div className="relative">
              <div className="absolute left-[17px] top-3 bottom-3 w-px bg-border" />
              <div className="space-y-0">
                {logs.map((log, i) => (
                  <LogEntry key={i} log={log} index={i} isLast={i === logs.length - 1} isFailed={log.node_id === failedNode} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Result JSON (collapsible) */}
      {result && (
        <details className="group">
          <summary className="text-lg font-semibold mb-3 cursor-pointer select-none list-none flex items-center gap-2">
            <span className="transition-transform group-open:rotate-90">▶</span>
            Raw Result JSON
          </summary>
          <pre className="rounded-lg border bg-muted p-4 text-xs overflow-auto max-h-96 mt-2">
            {JSON.stringify(result, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────────────────────────── */

function LiveLogTimeline({ entries }: { entries: LiveLogEntry[] }) {
  // Show last 50 entries, newest first
  const recent = useMemo(() => [...entries].reverse().slice(0, 50), [entries]);
  // Deduplicate consecutive same node_id for cleaner view
  const deduped = useMemo(() => {
    const result: (LiveLogEntry & { count: number })[] = [];
    for (const e of recent) {
      const last = result[result.length - 1];
      if (last && last.node_id === e.node_id) {
        last.count++;
      } else {
        result.push({ ...e, count: 1 });
      }
    }
    return result;
  }, [recent]);

  return (
    <div className="rounded-lg border bg-black/20 p-4 max-h-80 overflow-auto space-y-1">
      {deduped.map((entry, i) => (
        <div key={i} className="flex items-center gap-3 py-1 text-xs">
          <div className="h-1.5 w-1.5 rounded-full bg-cyan-400 flex-shrink-0" />
          <span className="font-mono text-cyan-300 min-w-[120px]">{entry.node_id}</span>
          {entry.count > 1 && (
            <Badge variant="outline" className="text-[10px] px-1 py-0">×{entry.count}</Badge>
          )}
          <span className="text-muted-foreground ml-auto">#{entry.nodes_done}</span>
        </div>
      ))}
    </div>
  );
}

function LogEntry({ log, index, isLast, isFailed }: { log: NodeExecutionLog; index: number; isLast: boolean; isFailed: boolean }) {
  const icon = ACTION_ICONS[log.action_type] ?? '⚙️';
  const dotColor = log.success
    ? 'bg-green-500 border-green-400'
    : 'bg-red-500 border-red-400';
  const bgColor = isFailed
    ? 'bg-red-950/30 border-red-800/50'
    : 'hover:bg-accent/50 border-transparent';

  return (
    <div className={`relative flex items-start gap-4 pl-2 py-2 rounded-lg border ${bgColor} transition-colors`}>
      <div className={`relative z-10 mt-1 h-[10px] w-[10px] rounded-full border-2 flex-shrink-0 ${dotColor}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-base" title={log.action_type}>{icon}</span>
          <span className="font-mono text-sm font-medium">{log.node_id}</span>
          <Badge variant="outline" className="text-[10px] px-1.5 py-0">
            {log.action_type}
          </Badge>
          <span className={`text-xs font-semibold ${log.success ? 'text-green-400' : 'text-red-400'}`}>
            {log.success ? 'OK' : 'FAIL'}
          </span>
          {log.duration_ms > 0 && (
            <span className="text-xs text-muted-foreground">
              {log.duration_ms > 1000 ? `${(log.duration_ms / 1000).toFixed(1)}s` : `${log.duration_ms}ms`}
            </span>
          )}
        </div>
        {log.error && (
          <p className="text-xs text-red-400 mt-1 font-mono break-all">{log.error}</p>
        )}
        {log.output != null && log.output !== '' && (
          <p className="text-xs text-muted-foreground mt-0.5 font-mono">→ {String(log.output)}</p>
        )}
      </div>
    </div>
  );
}

function MetricCard({ label, value, accent }: { label: string; value: string; accent: string }) {
  const colors: Record<string, string> = {
    cyan: 'text-cyan-300 border-cyan-800/50',
    blue: 'text-blue-300 border-blue-800/50',
    yellow: 'text-yellow-300 border-yellow-800/50',
    gray: 'text-gray-300 border-gray-700/50',
  };
  const c = colors[accent] ?? colors.gray;
  return (
    <div className={`rounded-lg border bg-black/20 p-3 ${c.split(' ')[1]}`}>
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`text-xl font-bold font-mono mt-1 ${c.split(' ')[0]}`}>{value}</p>
    </div>
  );
}

function InfoCard({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`font-medium text-sm mt-0.5 truncate ${mono ? 'font-mono' : ''}`}>{value}</p>
    </div>
  );
}

function formatElapsed(ms: number): string {
  if (ms <= 0) return '0s';
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function getDuration(started?: string | null, finished?: string | null): string {
  if (!started) return '—';
  const start = new Date(started).getTime();
  const end = finished ? new Date(finished).getTime() : Date.now();
  return formatElapsed(end - start);
}
