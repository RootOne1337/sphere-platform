'use client';

import { useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { ListTodo, Play, Clock, CalendarClock, ShieldAlert, CheckCircle2, Workflow } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import { TaskGanttChart } from '@/src/features/tasks/TaskGanttChart';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { toast } from 'sonner';

interface TaskItem {
  id: string;
  name: string;
  type: string;
  schedule: string;
  status: string;
  lastRun: string;
  nextRun: string;
  startTimeMs: number;
  durationMs: number | null;
}



export default function TaskEnginePage() {
  const router = useRouter();
  const [search, setSearch] = useState('');

  const { data: rawTasks = [], isLoading } = useQuery({
    queryKey: ['tasks-list'],
    queryFn: async () => {
      try {
        const { data } = await api.get('/tasks?per_page=100');
        // Backend returns { items: [...] }
        return data.items || [];
      } catch (e) {
        console.warn('Failed to fetch tasks (backend might be offline)', e);
        return [];
      }
    },
    refetchInterval: 5000
  });

  const tasks: TaskItem[] = useMemo(() => {
    return rawTasks.map((t: any) => {
      const isRunning = t.status === 'RUNNING' || t.status === 'ASSIGNED';
      const created = new Date(t.created_at);
      const isFailed = t.status === 'FAILED';

      return {
        id: t.id,
        name: t.name || `Task ${t.id.slice(0, 8)}`,
        type: t.priority > 0 ? 'CRON' : 'SCRIPT',
        schedule: 'Manual',
        status: t.status,
        lastRun: created.toLocaleString(),
        nextRun: isRunning ? 'In Progress...' : '-',
        startTimeMs: created.getTime(),
        durationMs: isRunning ? null : (t.finished_at && t.started_at ? new Date(t.finished_at).getTime() - new Date(t.started_at).getTime() : null)
      };
    });
  }, [rawTasks]);

  const runningTasks = useMemo(() => {
    return tasks
      .filter(t => t.status === 'RUNNING' || t.status === 'ASSIGNED' || t.status === 'QUEUED')
      .map(t => ({
        ...t,
        status: (t.status === 'FAILED' || t.status === 'ERROR') ? 'FAILED' :
          (t.status === 'COMPLETED' || t.status === 'SUCCESS') ? 'SUCCESS' :
            (t.status === 'RUNNING') ? 'RUNNING' : 'PENDING' as any
      }));
  }, [tasks]);

  return (
    <div className="flex flex-col h-full bg-card">
      <div className="px-6 py-5 border-b border-border bg-muted shrink-0">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <ListTodo className="w-5 h-5 text-primary" />
              <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">Task Engine</h1>
            </div>
            <p className="text-xs text-muted-foreground font-mono max-w-2xl">
              Unified orchestration layer for cron jobs, script execution, and N8N workflow schedules.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
            <Input
              placeholder="Filter tasks..."
              className="w-full sm:w-64 h-9 bg-black/50 border-border font-mono text-xs focus-visible:ring-primary/50"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Button variant="default" size="sm" className="h-9">
              <Workflow className="w-4 h-4 mr-2" /> New Workflow
            </Button>
          </div>
        </div>
      </div>

      <div className="p-6 flex-1 overflow-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-8">
          {/* Quick Stats — computed from real data */}
          <div className="border border-border bg-muted rounded-sm p-4 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase text-muted-foreground font-bold tracking-widest mb-1">Total Tasks</div>
              <div className="text-2xl font-mono font-bold text-foreground">{tasks.length}</div>
            </div>
            <CalendarClock className="w-8 h-8 text-primary/30" strokeWidth={1} />
          </div>
          <div className="border border-border bg-muted rounded-sm p-4 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase text-muted-foreground font-bold tracking-widest mb-1">Success Rate</div>
              <div className="text-2xl font-mono font-bold text-success">
                {tasks.length > 0
                  ? `${((tasks.filter(t => t.status === 'COMPLETED' || t.status === 'SUCCESS').length / tasks.length) * 100).toFixed(1)}%`
                  : '—'}
              </div>
            </div>
            <CheckCircle2 className="w-8 h-8 text-success/30" strokeWidth={1} />
          </div>
          <div className="border border-border bg-muted rounded-sm p-4 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase text-muted-foreground font-bold tracking-widest mb-1">Failed Tasks</div>
              <div className="text-2xl font-mono font-bold text-destructive">{tasks.filter(t => t.status === 'FAILED' || t.status === 'ERROR').length}</div>
            </div>
            <ShieldAlert className="w-8 h-8 text-destructive/30" strokeWidth={1} />
          </div>
        </div>

        {/* Top Dashboards: Gantt & Pipelines */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
          <div className="flex flex-col">
            <h2 className="text-xs font-mono font-bold tracking-widest text-muted-foreground mb-3 uppercase flex items-center gap-2">
              <Clock className="w-4 h-4" /> Live Execution Queue (Next 60s)
            </h2>
            <div className="flex-1 bg-card rounded-sm relative max-h-[250px] overflow-y-auto custom-scrollbar border-t border-border">
              {isLoading && <div className="p-4 text-center text-xs text-muted-foreground animate-pulse">Loading execution queue...</div>}
              {!isLoading && <TaskGanttChart tasks={runningTasks} />}
            </div>
          </div>

          <div className="flex flex-col">
            <h2 className="text-xs font-mono font-bold tracking-widest text-muted-foreground mb-3 uppercase flex items-center gap-2">
              <Workflow className="w-4 h-4" /> Active Pipeline
            </h2>
            <div className="flex-1 rounded-sm relative border-t border-border min-h-[150px] flex items-center justify-center">
              <div className="text-xs text-muted-foreground font-mono">No active pipeline running</div>
            </div>
          </div>
        </div>

        <div className="rounded-sm border border-border bg-card shadow-2xl overflow-x-auto custom-scrollbar mt-6">
          <table className="w-full min-w-[950px] text-left whitespace-nowrap table-fixed">
            <thead className="bg-[#151515]/90 border-b border-border text-[10px] uppercase font-mono tracking-widest font-bold text-muted-foreground sticky top-0 backdrop-blur-sm z-10">
              <tr>
                <th className="px-4 py-3 w-[120px]">Status</th>
                <th className="px-4 py-3 w-[250px]">Task Name</th>
                <th className="px-4 py-3 w-[120px]">Engine</th>
                <th className="px-4 py-3 w-[150px]">Crontab / Trigger</th>
                <th className="px-4 py-3 w-[150px]">Last Execution</th>
                <th className="px-4 py-3 w-[150px]">Next Projected</th>
                <th className="px-4 py-3 w-[100px] text-right">Interrupt</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#222]/50 font-mono text-xs text-foreground/80">
              {isLoading && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">Loading tasks...</td>
                </tr>
              )}
              {!isLoading && tasks.filter(t => t.name.toLowerCase().includes(search.toLowerCase()) || t.id.includes(search)).map((task) => (
                <tr key={task.id} onClick={() => router.push(`/tasks/${task.id}`)} className="hover:bg-muted transition-colors border-l-2 border-l-transparent group cursor-pointer">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {(task.status === 'ACTIVE' || task.status === 'RUNNING') && <div className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />}
                      {(task.status === 'PAUSED' || task.status === 'QUEUED') && <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground" />}
                      {(task.status === 'ERROR' || task.status === 'FAILED') && <div className="w-1.5 h-1.5 rounded-full bg-destructive animate-pulse" />}
                      <span className={`text-[10px] font-bold tracking-widest ${(task.status === 'ACTIVE' || task.status === 'RUNNING') ? 'text-success' :
                        (task.status === 'ERROR' || task.status === 'FAILED') ? 'text-destructive' : 'text-muted-foreground'
                        }`}>{task.status}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-bold text-foreground group-hover:text-primary transition-colors text-xs">{task.name}</div>
                    <div className="text-[10px] text-[#555] font-mono mt-0.5">{task.id}</div>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="outline" className={`text-[9px] bg-black ${task.type === 'CRON' ? 'border-primary text-primary' :
                      task.type === 'WORKFLOW' ? 'border-[#ff00ff] text-[#ff00ff]' :
                        'border-warning text-warning'
                      }`}>
                      {task.type}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-[#777] font-mono">{task.schedule}</td>
                  <td className="px-4 py-3 text-[#777] font-mono">{task.lastRun}</td>
                  <td className="px-4 py-3 font-bold text-[#aaa]">{task.nextRun}</td>
                  <td className="px-4 py-3 text-right">
                    <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-success hover:bg-success/10 rounded-sm">
                      <Play className="w-3.5 h-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

      </div>
    </div>
  );
}
