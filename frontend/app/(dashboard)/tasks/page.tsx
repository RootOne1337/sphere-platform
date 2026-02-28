'use client';

import { useState, useMemo } from 'react';
import { ListTodo, Play, Clock, CalendarClock, ShieldAlert, CheckCircle2, AlertTriangle, Workflow } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import { TaskGanttChart } from '@/src/features/tasks/TaskGanttChart';
import { WorkflowVisualizer } from '@/src/features/tasks/WorkflowVisualizer';

const MOCK_TASKS = [
  { id: 'TSK-9921', name: 'Nightly Config Backup', type: 'CRON', schedule: '0 2 * * *', status: 'ACTIVE', lastRun: '2 hours ago', nextRun: 'in 22 hours', successRate: 100 },
  { id: 'TSK-9922', name: 'Farm Auto-Reboot', type: 'WORKFLOW', schedule: 'Weekly (Sun)', status: 'ACTIVE', lastRun: '3 days ago', nextRun: 'in 4 days', successRate: 98 },
  { id: 'TSK-9923', name: 'Dormant Node Sweep', type: 'SCRIPT', schedule: 'Manual', status: 'PAUSED', lastRun: '15 days ago', nextRun: '-', successRate: 75 },
  { id: 'TSK-9924', name: 'VPN Certificate Rotation', type: 'CRON', schedule: '0 0 1 * *', status: 'ERROR', lastRun: 'Failed (OOM)', nextRun: 'Pending Retry', successRate: 40 },
];

const MOCK_RUNNING_TASKS: any[] = [
  { id: 'RUN-1', name: 'Sync DB Replicas (EU)', status: 'SUCCESS', startTimeMs: Date.now() - 50000, durationMs: 15000 },
  { id: 'RUN-2', name: 'Fetch Analytics', status: 'SUCCESS', startTimeMs: Date.now() - 40000, durationMs: 12000 },
  { id: 'RUN-3', name: 'WebHook Handler [GitHub]', status: 'FAILED', startTimeMs: Date.now() - 35000, durationMs: 5000 },
  { id: 'RUN-4', name: 'Farm Auto-Reboot [N8N]', status: 'RUNNING', startTimeMs: Date.now() - 15000, durationMs: null },
  { id: 'RUN-5', name: 'Device Config Push', status: 'RUNNING', startTimeMs: Date.now() - 5000, durationMs: null },
];

const MOCK_WORKFLOW_STEPS: any[] = [
  { id: 's1', name: 'Cron Trigger', type: 'TRIGGER', status: 'SUCCESS', duration: '12ms' },
  { id: 's2', name: 'Fetch Active Devices', type: 'ACTION', status: 'SUCCESS', duration: '245ms' },
  { id: 's3', name: 'Check Battery Level', type: 'CONDITION', status: 'SUCCESS', duration: '41ms' },
  { id: 's4', name: 'Send Reboot Signal via RabbitMQ', type: 'ACTION', status: 'RUNNING', duration: 'Running...' },
  { id: 's5', name: 'Wait For Reconnect', type: 'ACTION', status: 'PENDING' },
];

export default function TaskEnginePage() {
  const [search, setSearch] = useState('');

  return (
    <div className="flex flex-col h-full bg-[#0A0A0A]">
      <div className="px-6 py-5 border-b border-[#222] bg-[#111] shrink-0">
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

          <div className="flex items-center gap-3">
            <Input
              placeholder="Filter tasks..."
              className="w-64 h-9 bg-black/50 border-[#333] font-mono text-xs focus-visible:ring-primary/50"
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
          {/* Quick Stats */}
          <div className="border border-[#222] bg-[#111] rounded-sm p-4 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase text-muted-foreground font-bold tracking-widest mb-1">Active Schedules</div>
              <div className="text-2xl font-mono font-bold text-foreground">12</div>
            </div>
            <CalendarClock className="w-8 h-8 text-primary/30" strokeWidth={1} />
          </div>
          <div className="border border-[#222] bg-[#111] rounded-sm p-4 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase text-muted-foreground font-bold tracking-widest mb-1">24h Success Rate</div>
              <div className="text-2xl font-mono font-bold text-success">98.2%</div>
            </div>
            <CheckCircle2 className="w-8 h-8 text-success/30" strokeWidth={1} />
          </div>
          <div className="border border-[#222] bg-[#111] rounded-sm p-4 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase text-muted-foreground font-bold tracking-widest mb-1">Failed Tasks</div>
              <div className="text-2xl font-mono font-bold text-destructive">1</div>
            </div>
            <ShieldAlert className="w-8 h-8 text-destructive/30" strokeWidth={1} />
          </div>
        </div>

        {/* Top Dashboards: Gantt & Pipelines */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
          <div className="flex flex-col">
            <h2 className="text-xs font-mono font-bold tracking-widest text-[#888] mb-3 uppercase flex items-center gap-2">
              <Clock className="w-4 h-4" /> Live Execution Queue (Next 60s)
            </h2>
            <div className="flex-1 bg-[#0A0A0A] rounded-sm relative max-h-[250px] overflow-y-auto custom-scrollbar border-t border-[#222]">
              <TaskGanttChart tasks={MOCK_RUNNING_TASKS} />
            </div>
          </div>

          <div className="flex flex-col">
            <h2 className="text-xs font-mono font-bold tracking-widest text-[#888] mb-3 uppercase flex items-center gap-2">
              <Workflow className="w-4 h-4" /> Active Pipeline (Farm Auto-Reboot)
            </h2>
            <div className="flex-1 rounded-sm relative border-t border-[#222] min-h-[150px]">
              <WorkflowVisualizer steps={MOCK_WORKFLOW_STEPS} />
            </div>
          </div>
        </div>

        <div className="rounded-sm border border-[#222] bg-[#0f0f0f] shadow-2xl overflow-hidden mt-6">
          <table className="w-full text-left whitespace-nowrap table-fixed">
            <thead className="bg-[#151515]/90 border-b border-[#222] text-[10px] uppercase font-mono tracking-widest font-bold text-muted-foreground sticky top-0 backdrop-blur-sm z-10">
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
              {MOCK_TASKS.filter(t => t.name.toLowerCase().includes(search.toLowerCase())).map((task) => (
                <tr key={task.id} className="hover:bg-[#151515] transition-colors border-l-2 border-l-transparent group cursor-pointer">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {task.status === 'ACTIVE' && <div className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />}
                      {task.status === 'PAUSED' && <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground" />}
                      {task.status === 'ERROR' && <div className="w-1.5 h-1.5 rounded-full bg-destructive animate-pulse" />}
                      <span className={`text-[10px] font-bold tracking-widest ${task.status === 'ACTIVE' ? 'text-success' :
                        task.status === 'ERROR' ? 'text-destructive' : 'text-[#888]'
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
