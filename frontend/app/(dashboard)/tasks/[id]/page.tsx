'use client';
import { use } from 'react';
import { useTask, useTaskLogs, useCancelTask } from '@/lib/hooks/useTasks';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import Link from 'next/link';

interface Props {
  params: Promise<{ id: string }>;
}

export default function TaskDetailPage({ params }: Props) {
  const { id } = use(params);
  const { data: task, isLoading } = useTask(id);
  const { data: logs } = useTaskLogs(id);
  const cancelTask = useCancelTask();

  if (isLoading) {
    return <div className="p-6 text-muted-foreground">Loading…</div>;
  }

  if (!task) {
    return <div className="p-6 text-muted-foreground">Task not found</div>;
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Task Detail</h1>
          <p className="text-sm text-muted-foreground font-mono">{task.id}</p>
        </div>
        <div className="flex gap-2">
          {['QUEUED', 'ASSIGNED'].includes(task.status) && (
            <Button
              variant="destructive"
              onClick={() => cancelTask.mutate(task.id)}
              disabled={cancelTask.isPending}
            >
              Cancel Task
            </Button>
          )}
          <Button asChild variant="outline">
            <Link href="/tasks">Back to Tasks</Link>
          </Button>
        </div>
      </div>

      {/* Info grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <InfoCard label="Status" value={task.status} />
        <InfoCard label="Priority" value={String(task.priority)} />
        <InfoCard label="Device" value={task.device_id.slice(0, 12) + '…'} />
        <InfoCard label="Script" value={task.script_id.slice(0, 12) + '…'} />
        <InfoCard label="Created" value={new Date(task.created_at).toLocaleString()} />
        <InfoCard label="Started" value={task.started_at ? new Date(task.started_at).toLocaleString() : '—'} />
        <InfoCard label="Finished" value={task.finished_at ? new Date(task.finished_at).toLocaleString() : '—'} />
        <InfoCard label="Batch" value={task.batch_id?.slice(0, 12) ?? '—'} />
      </div>

      {/* Error */}
      {task.error_message && (
        <div className="rounded border border-red-800 bg-red-950 p-4">
          <p className="text-sm font-medium text-red-400">Error</p>
          <pre className="text-xs text-red-300 mt-1 whitespace-pre-wrap">{task.error_message}</pre>
        </div>
      )}

      {/* Execution Logs */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Execution Logs</h2>
        {!logs || logs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No execution logs yet</p>
        ) : (
          <div className="space-y-2">
            {logs.map((log, i) => (
              <div key={i} className="rounded border p-3 text-sm">
                <div className="flex items-center gap-3 mb-1">
                  <Badge variant="outline">{log.node_type}</Badge>
                  <span className="font-mono text-xs text-muted-foreground">{log.node_id}</span>
                  <span className={`text-xs font-medium ${log.status === 'success' ? 'text-green-400' : log.status === 'failed' ? 'text-red-400' : 'text-yellow-400'}`}>
                    {log.status}
                  </span>
                </div>
                {log.error && (
                  <p className="text-xs text-red-400 mt-1">{log.error}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Result JSON */}
      {task.result && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Result</h2>
          <pre className="rounded border bg-muted p-4 text-xs overflow-auto max-h-60">
            {JSON.stringify(task.result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-medium text-sm mt-0.5 truncate">{value}</p>
    </div>
  );
}
