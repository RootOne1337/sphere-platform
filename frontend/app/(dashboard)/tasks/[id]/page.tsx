'use client';

import { use, useState, useMemo } from 'react';
import {
  useTask,
  useTaskLogs,
  useCancelTask,
  useStopTask,
  useTaskProgress,
  useCreateTask,
  useTaskLiveLogs,
  type NodeExecutionLog,
  type LiveLogEntry,
} from '@/lib/hooks/useTasks';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import Link from 'next/link';
import {
  Play,
  Square,
  Ban,
  RotateCcw,
  ArrowLeft,
  Server,
  FileCode2,
  ListOrdered,
  Clock,
  CheckCircle2,
  XCircle,
  Activity,
  Box,
  Hash,
  MonitorSmartphone,
  ChevronRight,
  Terminal,
  ActivitySquare
} from 'lucide-react';

interface Props {
  params: Promise<{ id: string }>;
}

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  queued: { label: 'Queued', color: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/20' },
  assigned: { label: 'Assigned', color: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/20' },
  running: { label: 'Running', color: 'text-cyan-400', bg: 'bg-cyan-500/10', border: 'border-cyan-500/20' },
  completed: { label: 'Completed', color: 'text-green-400', bg: 'bg-green-500/10', border: 'border-green-500/20' },
  failed: { label: 'Failed', color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/20' },
  cancelled: { label: 'Cancelled', color: 'text-gray-400', bg: 'bg-gray-500/10', border: 'border-gray-500/20' },
};

const ACTION_ICONS: Record<string, string> = {
  start: '🚀', end: '🏁', sleep: '⏳', condition: '🔀', tap: '👆',
  find_element: '🔍', swipe: '👋', input_text: '⌨️', screenshot: '📸',
  launch_app: '📱', back: '◀️', home: '🏠', scroll: '📜',
};

// Main Component
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

  const resultNodeLogs = (task?.result as Record<string, unknown> | null)?.node_logs as NodeExecutionLog[] | undefined;
  const logs = (logsFromApi && logsFromApi.length > 0) ? logsFromApi : resultNodeLogs ?? logsFromApi;

  if (isLoading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[50vh]">
        <div className="flex flex-col items-center gap-4 text-muted-foreground">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="animate-pulse tracking-widest text-xs uppercase font-mono">Loading telemetry...</p>
        </div>
      </div>
    );
  }

  if (!task) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[50vh]">
        <div className="flex flex-col items-center gap-4 text-muted-foreground bg-card p-8 rounded-xl border border-border">
          <XCircle className="w-12 h-12 text-muted-foreground/50" />
          <p className="font-mono">Task not found</p>
          <Button asChild variant="outline" className="mt-4"><Link href="/tasks">Return to Terminal</Link></Button>
        </div>
      </div>
    );
  }

  const statusCfg = STATUS_CONFIG[task.status] ?? STATUS_CONFIG.queued;
  const result = task.result as Record<string, unknown> | null;

  const nodesExecuted = liveProgress?.nodes_done ?? (result?.nodes_executed as number) ?? logs?.length ?? 0;
  const totalNodes = liveProgress?.total_nodes ?? (result?.total_nodes as number) ?? (result?.node_logs as unknown[])?.length ?? 0;
  const cycles = liveProgress?.cycles ?? (totalNodes > 0 ? Math.floor(nodesExecuted / totalNodes) : 0);
  const currentNode = liveProgress?.current_node ?? '';
  const failedNode = result?.failed_node as string | undefined;

  const elapsedMs = liveProgress?.started_at
    ? Date.now() - liveProgress.started_at * 1000
    : task.started_at
      ? Date.now() - new Date(task.started_at).getTime()
      : 0;

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto animate-in fade-in duration-500">
      {/* ── Header Area ────────────────────────────────────────────────────────── */}
      <div className="relative rounded-2xl overflow-hidden border border-border bg-card/50 backdrop-blur-xl">
        {/* Dynamic ambient background based on status */}
        {isActive && (
          <div className="absolute inset-0 bg-gradient-to-r from-cyan-500/10 via-transparent to-transparent opacity-50" />
        )}
        {(task.status === 'completed') && (
          <div className="absolute inset-0 bg-gradient-to-r from-green-500/10 via-transparent to-transparent opacity-50" />
        )}
        {(task.status === 'failed') && (
          <div className="absolute inset-0 bg-gradient-to-r from-red-500/10 via-transparent to-transparent opacity-50" />
        )}

        <div className="relative p-6 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <Link href="/tasks" className="p-2 hover:bg-white/5 rounded-lg transition-colors text-muted-foreground hover:text-foreground">
                <ArrowLeft className="w-5 h-5" />
              </Link>
              <h1 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
                Task Detail
                <span className={`inline-flex items-center gap-2 px-3 py-1 rounded-md text-xs font-semibold uppercase tracking-wider border ${statusCfg.bg} ${statusCfg.color} ${statusCfg.border}`}>
                  {isActive && (
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75" />
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-current" />
                    </span>
                  )}
                  {statusCfg.label}
                </span>
              </h1>
            </div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground ml-11">
              <Hash className="w-4 h-4 opacity-50" />
              <span className="font-mono tracking-wider select-all">{task.id}</span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 pl-11 md:pl-0">
            {task.status === 'running' && (
              <Button
                variant="destructive"
                onClick={() => stopTask.mutate(task.id)}
                disabled={stopTask.isPending}
                className="gap-2 shadow-[0_0_20px_rgba(239,68,68,0.3)] hover:shadow-[0_0_30px_rgba(239,68,68,0.5)] transition-all bg-red-600/90 hover:bg-red-500 text-white"
              >
                <Square className="w-4 h-4 fill-current" />
                {stopTask.isPending ? 'Halting...' : 'Force Stop'}
              </Button>
            )}

            {['queued', 'assigned'].includes(task.status) && (
              <Button
                variant="destructive"
                onClick={() => cancelTask.mutate(task.id)}
                disabled={cancelTask.isPending}
                className="gap-2 bg-red-950 text-red-400 hover:bg-red-900/80 border border-red-900/50"
              >
                <Ban className="w-4 h-4" />
                {cancelTask.isPending ? 'Aborting...' : 'Cancel Task'}
              </Button>
            )}

            {['completed', 'failed', 'cancelled', 'timeout'].includes(task.status) && (
              <Button
                variant="default"
                disabled={restarting}
                className="gap-2 bg-emerald-600 hover:bg-emerald-500 text-white shadow-[0_0_20px_rgba(16,185,129,0.2)] hover:shadow-[0_0_30px_rgba(16,185,129,0.4)] transition-all"
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
                <RotateCcw className={`w-4 h-4 ${restarting ? 'animate-spin' : ''}`} />
                {restarting ? 'Deploying...' : 'Restart Task'}
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* ── Quick Info Grid ────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
        <InfoCard icon={ActivitySquare} label="Priority" value={String(task.priority)} />
        <InfoCard icon={MonitorSmartphone} label="Device ID" value={task.device_id} isMono />
        <InfoCard icon={FileCode2} label="Script ID" value={task.script_id} isMono />
        <InfoCard icon={Box} label="Batch ID" value={task.batch_id || 'N/A'} isMono />
        {task.wave_index != null && <InfoCard icon={ListOrdered} label="Wave Index" value={String(task.wave_index)} />}
        <InfoCard icon={Clock} label="Created At" value={new Date(task.created_at).toLocaleString()} />
        <InfoCard icon={Play} label="Started At" value={task.started_at ? new Date(task.started_at).toLocaleString() : '—'} />
        <InfoCard icon={CheckCircle2} label="Finished At" value={task.finished_at ? new Date(task.finished_at).toLocaleString() : '—'} />
        <InfoCard icon={Server} label="Duration" value={getDuration(task.started_at, task.finished_at)} highlight />
      </div>

      {/* Input Params */}
      {task.input_params && Object.keys(task.input_params).length > 0 && (
        <div className="rounded-xl border border-border bg-card/50 p-5">
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3 flex items-center gap-2">
            <Terminal className="w-4 h-4" /> Input Parameters
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {Object.entries(task.input_params).map(([key, val]) => (
              <div key={key} className="bg-black/20 rounded-lg p-3 border border-white/5">
                <p className="text-xs text-muted-foreground font-mono">{key}</p>
                <p className="font-mono text-sm mt-1 truncate text-cyan-200">{String(val)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error Banner */}
      {task.error_message && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-5 backdrop-blur-sm relative overflow-hidden">
          <div className="absolute top-0 left-0 w-1 h-full bg-red-500" />
          <div className="flex items-start gap-4">
            <XCircle className="w-6 h-6 text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="font-semibold text-red-300">Execution Failed</h3>
              <pre className="text-xs text-red-200/80 mt-2 font-mono whitespace-pre-wrap break-all bg-black/40 p-3 rounded-lg border border-red-500/20">{task.error_message}</pre>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ── Main Left Column (Execution & Logs) ────────────────────────────── */}
        <div className="lg:col-span-2 space-y-6">

          {/* Live Execution Highlight (Running) */}
          {task.status === 'running' && (
            <div className="rounded-2xl border border-cyan-500/30 bg-gradient-to-br from-cyan-950/40 to-blue-950/20 p-6 relative overflow-hidden shadow-[0_0_40px_rgba(6,182,212,0.1)]">
              <div className="absolute -top-24 -right-24 w-48 h-48 bg-cyan-500/20 rounded-full blur-[80px] pointer-events-none" />

              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  <Activity className="w-5 h-5 text-cyan-400" />
                  <h2 className="text-lg font-semibold text-cyan-300 tracking-wide">Live Telemetry</h2>
                </div>
                <div className="bg-black/40 px-3 py-1.5 rounded-md border border-white/10 font-mono text-cyan-300 text-sm">
                  {formatElapsed(elapsedMs)}
                </div>
              </div>

              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                <MetricCard label="Nodes Executed" value={String(nodesExecuted)} accent="cyan" />
                <MetricCard label="Cycles" value={String(cycles)} accent="blue" />
                <MetricCard label="Total Nodes" value={String(totalNodes)} accent="purple" />
                <MetricCard label="Pass Rate" value={(nodesExecuted > 0 ? '100%' : '0%')} accent="green" /> {/* Approximated for UI aesthetics */}
              </div>

              {currentNode && (
                <div className="flex items-center gap-3 bg-black/40 border border-cyan-500/20 rounded-xl px-5 py-3 backdrop-blur-md">
                  <div className="h-2 w-2 rounded-full bg-cyan-400 animate-ping flex-shrink-0" />
                  <span className="text-sm text-cyan-100/70">Processing Target:</span>
                  <span className="text-sm font-mono tracking-wider text-cyan-300 ml-auto break-all text-right">{currentNode}</span>
                </div>
              )}

              <div className="mt-5 h-1.5 rounded-full bg-black/50 overflow-hidden relative">
                <div className="absolute top-0 bottom-0 rounded-full bg-gradient-to-r from-cyan-600 via-cyan-400 to-blue-500 animate-indeterminate" style={{ width: '30%' }} />
              </div>
            </div>
          )}

          {/* Execution Logs Timeline (Completed/Failed) */}
          {!isActive && (
            <div className="rounded-2xl border border-border bg-card/30 backdrop-blur-sm overflow-hidden flex flex-col">
              <div className="bg-muted/30 p-4 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Terminal className="w-5 h-5 text-muted-foreground" />
                  <h2 className="text-base font-semibold">Execution Timeline</h2>
                </div>
                <div className="flex items-center gap-3 text-sm font-mono">
                  {nodesExecuted > 0 && <span className="text-green-400">{nodesExecuted} passed</span>}
                  {totalNodes > 0 && <span className="text-muted-foreground ml-2">Total: {totalNodes}</span>}
                  {cycles > 0 && <span className="text-blue-400 ml-2">Cycles: {cycles}</span>}
                </div>
              </div>

              <div className="p-6">
                {(!logs || logs.length === 0) ? (
                  <div className="py-12 flex flex-col items-center justify-center text-muted-foreground border border-dashed border-border rounded-xl">
                    <ActivitySquare className="w-10 h-10 opacity-20 mb-3" />
                    <p className="text-sm">No node execution data available.</p>
                  </div>
                ) : (
                  <div className="relative">
                    <div className="absolute left-[20px] top-6 bottom-6 w-px bg-gradient-to-b from-transparent via-border to-transparent" />
                    <div className="space-y-4">
                      {logs.map((log, i) => (
                        <LogEntry key={i} log={log} isFailed={log.node_id === failedNode} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Raw Result Payload */}
          {result && !isActive && (
            <div className="rounded-2xl border border-border bg-card/30 backdrop-blur-sm overflow-hidden">
              <details className="group">
                <summary className="p-4 bg-muted/30 border-b border-border text-base font-semibold cursor-pointer select-none list-none flex items-center gap-3 hover:bg-muted/50 transition-colors">
                  <ChevronRight className="w-5 h-5 text-muted-foreground transition-transform duration-300 group-open:rotate-90" />
                  <FileCode2 className="w-5 h-5 text-muted-foreground" />
                  Final Execution Result (JSON)
                </summary>
                <div className="p-0 bg-[#0d1117] overflow-x-auto">
                  <pre className="p-6 text-xs text-gray-300 font-mono leading-relaxed">
                    {JSON.stringify(result, null, 2)}
                  </pre>
                </div>
              </details>
            </div>
          )}
        </div>

        {/* ── Right Column (Live Log stream & Additional context) ────────────── */}
        <div className="space-y-6">
          {isActive && liveLogs && (
            <div className="rounded-2xl border border-border bg-card/40 backdrop-blur-md overflow-hidden flex flex-col h-[600px] sticky top-6">
              <div className="p-4 bg-black/40 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-cyan-500 animate-pulse" />
                  <h3 className="font-semibold text-sm">Live Feed</h3>
                </div>
                <Badge variant="outline" className="bg-black/50 text-[10px] font-mono font-normal">
                  {liveLogs.length} events
                </Badge>
              </div>
              <div className="flex-1 overflow-auto p-4 custom-scrollbar">
                <LiveLogTimeline entries={liveLogs} />
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────────────────────────── */

function InfoCard({ icon: Icon, label, value, isMono, highlight }: { icon: any, label: string, value: string, isMono?: boolean, highlight?: boolean }) {
  return (
    <div className={`rounded-xl border border-white/5 bg-black/20 p-4 transition-colors hover:bg-black/30 group ${highlight ? 'border-primary/20 bg-primary/5' : ''}`}>
      <div className="flex items-center justify-between mb-2">
        <p className={`text-xs uppercase tracking-wider font-semibold ${highlight ? 'text-primary' : 'text-muted-foreground'} group-hover:text-foreground transition-colors`}>{label}</p>
        <Icon className={`w-4 h-4 ${highlight ? 'text-primary' : 'text-muted-foreground opacity-50'}`} />
      </div>
      <p className={`text-sm mt-1 truncate ${isMono ? 'font-mono text-cyan-100/80 tracking-tight' : 'font-medium text-foreground'}`} title={value}>
        {value}
      </p>
    </div>
  );
}

function MetricCard({ label, value, accent }: { label: string; value: string; accent: 'cyan' | 'blue' | 'purple' | 'green' }) {
  const configs = {
    cyan: 'from-cyan-500/20 to-cyan-500/5 text-cyan-300 border-cyan-500/20',
    blue: 'from-blue-500/20 to-blue-500/5 text-blue-300 border-blue-500/20',
    purple: 'from-purple-500/20 to-purple-500/5 text-purple-300 border-purple-500/20',
    green: 'from-emerald-500/20 to-emerald-500/5 text-emerald-300 border-emerald-500/20',
  };
  const c = configs[accent];
  return (
    <div className={`rounded-xl bg-gradient-to-b border p-4 backdrop-blur-sm shadow-inner ${c}`}>
      <p className="text-[10px] uppercase tracking-wider opacity-70 mb-1">{label}</p>
      <p className="text-2xl font-bold font-mono tracking-tight">{value}</p>
    </div>
  );
}

function LiveLogTimeline({ entries }: { entries: LiveLogEntry[] }) {
  const recent = useMemo(() => [...entries].reverse().slice(0, 100), [entries]);
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

  if (deduped.length === 0) {
    return <div className="text-center text-xs text-muted-foreground mt-10">Waiting for stream...</div>;
  }

  return (
    <div className="space-y-2">
      {deduped.map((entry, i) => (
        <div key={i} className="flex items-start gap-3 p-2 rounded-lg hover:bg-white/5 transition-colors group">
          <div className="mt-1.5 h-1.5 w-1.5 rounded-full bg-cyan-500 shadow-[0_0_8px_rgba(6,182,212,0.8)] flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex justify-between items-center gap-2">
              <span className="font-mono text-cyan-200 text-xs break-all">{entry.node_id}</span>
              <span className="text-[10px] text-muted-foreground font-mono bg-black/50 px-1.5 py-0.5 rounded opacity-50 group-hover:opacity-100 transition-opacity whitespace-nowrap">
                #{entry.nodes_done}
              </span>
            </div>
            {entry.count > 1 && (
              <Badge variant="outline" className="mt-1 bg-blue-500/10 text-blue-300 border-blue-500/20 text-[9px] px-1 py-0 uppercase tracking-widest">
                Repeated {entry.count}x
              </Badge>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function LogEntry({ log, isFailed }: { log: NodeExecutionLog; isFailed: boolean }) {
  const icon = ACTION_ICONS[log.action_type] ?? '⚙️';
  const dotColor = log.success
    ? 'bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)] border-emerald-950'
    : 'bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.5)] border-red-950';

  const containerStyle = isFailed
    ? 'bg-red-950/20 border border-red-900/40 rounded-xl p-4'
    : 'bg-transparent border border-transparent rounded-xl p-4 hover:bg-white/5';

  return (
    <div className={`relative flex gap-5 transition-all duration-300 ${containerStyle} group`}>
      <div className={`relative z-10 mt-1.5 h-3 w-3 rounded-full border-2 flex-shrink-0 ${dotColor} transition-transform group-hover:scale-125`} />

      <div className="flex-1 min-w-0 space-y-2">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-lg bg-black/40 border border-white/5 flex items-center justify-center text-lg shadow-inner">
              {icon}
            </div>
            <div>
              <h4 className="font-mono text-sm font-semibold text-gray-200 tracking-tight">{log.node_id}</h4>
              <div className="flex items-center gap-2 mt-0.5">
                <Badge variant="outline" className="text-[9px] px-1.5 py-0 bg-white/5 uppercase tracking-wider">
                  {log.action_type}
                </Badge>
                <div className={`text-[10px] font-bold uppercase tracking-widest ${log.success ? 'text-emerald-500' : 'text-red-500'}`}>
                  {log.success ? 'Success' : 'Failure'}
                </div>
              </div>
            </div>
          </div>

          <div className="text-right flex flex-col items-end">
            {log.duration_ms > 0 && (
              <span className="text-[10px] text-muted-foreground font-mono bg-black/30 px-2 py-1 rounded-md border border-white/5">
                {log.duration_ms > 1000 ? `${(log.duration_ms / 1000).toFixed(2)}s` : `${log.duration_ms}ms`}
              </span>
            )}
            {log.started_at && (
              <span className="text-[10px] text-muted-foreground/50 mt-1">
                {new Date(log.started_at).toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>

        {log.error && (
          <div className="mt-3 p-3 bg-red-950/40 border border-red-900/50 rounded-lg backdrop-blur-sm">
            <p className="text-xs text-red-300 font-mono whitespace-pre-wrap break-words">{log.error}</p>
          </div>
        )}

        {log.output != null && log.output !== '' && (
          <details className="mt-2 text-xs group/out">
            <summary className="cursor-pointer text-muted-foreground hover:text-cyan-400 transition-colors list-none flex items-center gap-2 font-mono">
              <span className="text-[10px] opacity-70 group-open/out:rotate-90 transition-transform">▶</span>
              View Output Data
            </summary>
            <div className="mt-2 bg-black/50 border border-white/5 p-3 rounded-lg overflow-x-auto text-cyan-100/70 font-mono leading-relaxed">
              {typeof log.output === 'object' ? JSON.stringify(log.output, null, 2) : String(log.output)}
            </div>
          </details>
        )}

        {log.screenshot_key && (
          <div className="mt-3 inline-block">
            <div className="relative group/img overflow-hidden rounded-lg border border-white/10 shadow-lg cursor-zoom-in">
              <img
                src={`/api/files/${log.screenshot_key}`}
                alt="Execution Screenshot"
                className="max-h-64 object-contain bg-black/50 transition-transform duration-500 group-hover/img:scale-105"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = 'none';
                  (e.target as HTMLImageElement).parentElement!.innerHTML = '<span class="text-xs text-muted-foreground p-4 block bg-black/50">Screenshot unavailable</span>';
                }}
              />
              <div className="absolute inset-0 bg-cyan-500/0 group-hover/img:bg-cyan-500/10 transition-colors" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function formatElapsed(ms: number): string {
  if (ms <= 0) return '00:00:00';
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function getDuration(started?: string | null, finished?: string | null): string {
  if (!started) return '—';
  const start = new Date(started).getTime();
  const end = finished ? new Date(finished).getTime() : Date.now();
  return formatElapsed(end - start);
}
