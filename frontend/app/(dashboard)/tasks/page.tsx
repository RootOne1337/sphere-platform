'use client';
import { useState } from 'react';
import { useTasks, useCancelTask, useStopTask } from '@/lib/hooks/useTasks';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import Link from 'next/link';

const STATUS_COLORS: Record<string, string> = {
  queued: 'bg-yellow-500/20 text-yellow-400',
  assigned: 'bg-blue-500/20 text-blue-400',
  running: 'bg-cyan-500/20 text-cyan-400',
  completed: 'bg-green-500/20 text-green-400',
  failed: 'bg-red-500/20 text-red-400',
  cancelled: 'bg-gray-500/20 text-gray-400',
};

export default function TasksPage() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const { data, isLoading } = useTasks({
    page,
    per_page: 50,
    status: statusFilter || undefined,
  });
  const cancelTask = useCancelTask();
  const stopTask = useStopTask();

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Tasks</h1>
        <div className="flex gap-2">
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
            className="rounded border bg-background px-3 py-1.5 text-sm"
          >
            <option value="">All statuses</option>
            <option value="queued">Queued</option>
            <option value="assigned">Assigned</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <>
          <div className="rounded border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="p-3">Status</th>
                  <th className="p-3">Device</th>
                  <th className="p-3">Script</th>
                  <th className="p-3">Priority</th>
                  <th className="p-3">Created</th>
                  <th className="p-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((task) => (
                  <tr key={task.id} className="border-b hover:bg-accent/50">
                    <td className="p-3">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[task.status] ?? ''}`}>
                        {task.status}
                      </span>
                    </td>
                    <td className="p-3 font-mono text-xs">{task.device_id.slice(0, 8)}…</td>
                    <td className="p-3 font-mono text-xs">{task.script_id.slice(0, 8)}…</td>
                    <td className="p-3">{task.priority}</td>
                    <td className="p-3 text-xs text-muted-foreground">
                      {new Date(task.created_at).toLocaleString()}
                    </td>
                    <td className="p-3 flex gap-2">
                      <Button asChild size="sm" variant="outline">
                        <Link href={`/tasks/${task.id}`}>Details</Link>
                      </Button>
                      {task.status === 'running' && (
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => stopTask.mutate(task.id)}
                          disabled={stopTask.isPending}
                          className="gap-1.5 shadow-sm shadow-red-500/20"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
                          Stop
                        </Button>
                      )}
                      {['queued', 'assigned'].includes(task.status) && (
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => cancelTask.mutate(task.id)}
                          disabled={cancelTask.isPending}
                        >
                          Cancel
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
                {data?.items.length === 0 && (
                  <tr>
                    <td colSpan={6} className="p-6 text-center text-muted-foreground">
                      No tasks found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {data && data.pages > 1 && (
            <div className="flex items-center gap-2 justify-center">
              <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                Prev
              </Button>
              <span className="text-sm text-muted-foreground">
                {page} / {data.pages}
              </span>
              <Button size="sm" variant="outline" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
