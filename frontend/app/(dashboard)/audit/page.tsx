'use client';
import { useState, useMemo } from 'react';
import { Shield, Filter, AlertTriangle, CheckCircle2, XCircle, Info, Download } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { useAuthStore } from '@/lib/store';
import { AuditQueryBuilder } from '@/src/features/audit/AuditQueryBuilder';
import { AuditDrawer } from '@/src/features/audit/AuditDrawer';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

/** Формат строки в таблице audit-логов */
interface AuditEvent {
  id: string;
  timestamp: string;
  user: string;
  action: string;
  resource: string;
  status: 'SUCCESS' | 'FAILED' | 'WARNING';
  ip: string;
}

export default function AuditLogsPage() {
  const { data: events = [], isLoading } = useQuery<AuditEvent[]>({
    queryKey: ['audit-logs'],
    queryFn: async () => {
      try {
        const { data } = await api.get('/audit/logs');
        const items = data.items ? data.items : (Array.isArray(data) ? data : []);
        return items.map((item: any) => ({
          id: item.id,
          timestamp: item.created_at || item.timestamp,
          user: item.user_id || item.user || 'system',
          action: item.action,
          resource: item.resource_type || item.resource || '',
          status: item.status || 'SUCCESS',
          ip: item.ip_address || item.ip || '',
        }));
      } catch (e) {
        console.warn('Failed to fetch audit logs (backend might be offline)', e);
        return [];
      }
    }
  });
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);

  // Панель фильтров
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filterStatus, setFilterStatus] = useState<string>('');
  const [filterAction, setFilterAction] = useState<string>('');
  const [filterUser, setFilterUser] = useState<string>('');

  // Уникальные значения для дропдаунов фильтров
  const uniqueActions = useMemo(() => [...new Set(events.map((e) => e.action))].sort(), [events]);
  const uniqueUsers = useMemo(() => [...new Set(events.map((e) => e.user))].sort(), [events]);

  const StatusIcon = ({ status }: { status: AuditEvent['status'] }) => {
    switch (status) {
      case 'SUCCESS': return <CheckCircle2 className="w-4 h-4 text-success" />;
      case 'FAILED': return <XCircle className="w-4 h-4 text-destructive" />;
      case 'WARNING': return <AlertTriangle className="w-4 h-4 text-warning" />;
      default: return <Info className="w-4 h-4 text-muted-foreground" />;
    }
  };

  // Simple parser for our query builder syntax -> "status:FAILED user:admin"
  const filteredEvents = useMemo(() => {
    let result = events;

    // Фильтры из панели
    if (filterStatus) {
      result = result.filter((e) => e.status === filterStatus);
    }
    if (filterAction) {
      result = result.filter((e) => e.action === filterAction);
    }
    if (filterUser) {
      result = result.filter((e) => e.user === filterUser);
    }

    if (!searchQuery.trim()) return result;

    const terms = searchQuery.toLowerCase().split(' ').filter(Boolean);
    return result.filter(e => {
      return terms.every(term => {
        if (term.includes(':')) {
          const [key, val] = term.split(':');
          if (key === 'status') return (e.status || '').toLowerCase() === val;
          if (key === 'action') return (e.action || '').toLowerCase().includes(val);
          if (key === 'user') return (e.user || '').toLowerCase().includes(val);
        }
        // Fallback global search
        return JSON.stringify(e).toLowerCase().includes(term);
      });
    });
  }, [events, searchQuery, filterStatus, filterAction, filterUser]);

  /** Экспорт отфильтрованных событий в CSV */
  const handleExportCSV = () => {
    if (filteredEvents.length === 0) return;
    const headers = ['Timestamp', 'Status', 'Action', 'User', 'Resource', 'IP'];
    const rows = filteredEvents.map((e) => [
      e.timestamp,
      e.status,
      e.action,
      e.user,
      e.resource,
      e.ip,
    ]);
    const csv = [headers, ...rows].map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit-export-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col h-full bg-card relative overflow-hidden">

      {/* Header */}
      <div className="px-6 py-5 border-b border-border bg-muted flex flex-col md:flex-row md:items-center justify-between gap-4 shrink-0 z-10">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Shield className="w-5 h-5 text-primary" />
            <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">Security Audit</h1>
          </div>
          <p className="text-[10px] text-muted-foreground max-w-xl font-mono uppercase tracking-widest mt-1">
            Immutable log of all user actions, system events, and security access attempts.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 md:gap-3">
          <div className="w-full sm:w-auto">
            <AuditQueryBuilder value={searchQuery} onChange={setSearchQuery} />
          </div>

          <Button variant="outline" size="sm" className="h-9 border-border hover:bg-border" onClick={() => setFiltersOpen(!filtersOpen)}>
            <Filter className="w-4 h-4 mr-2" />
            <span className="text-[10px] uppercase font-bold tracking-widest">Filters{(filterStatus || filterAction || filterUser) ? ' ●' : ''}</span>
          </Button>
          <Button variant="default" size="sm" className="h-9 bg-primary/20 text-primary hover:bg-primary/30 border border-primary/50" onClick={handleExportCSV} disabled={filteredEvents.length === 0}>
            <Download className="w-4 h-4 mr-2" />
            <span className="text-[10px] uppercase font-bold tracking-widest">Export CSV ({filteredEvents.length})</span>
          </Button>
        </div>
      </div>

      {/* Table Area */}
      <div className="flex-1 overflow-auto p-6 relative">
        {/* Панель фильтров */}
        {filtersOpen && (
          <div className="mb-4 flex items-center gap-3 flex-wrap p-3 bg-muted border border-border rounded-sm">
            <div className="flex items-center gap-1.5">
              <label className="text-[10px] font-mono text-muted-foreground uppercase">Status:</label>
              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value)}
                className="px-2 py-1 rounded border border-border bg-background text-xs font-mono"
              >
                <option value="">Все</option>
                <option value="SUCCESS">SUCCESS</option>
                <option value="FAILED">FAILED</option>
                <option value="WARNING">WARNING</option>
              </select>
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-[10px] font-mono text-muted-foreground uppercase">Action:</label>
              <select
                value={filterAction}
                onChange={(e) => setFilterAction(e.target.value)}
                className="px-2 py-1 rounded border border-border bg-background text-xs font-mono"
              >
                <option value="">Все</option>
                {uniqueActions.map((a) => (
                  <option key={a} value={a}>{a}</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-[10px] font-mono text-muted-foreground uppercase">User:</label>
              <select
                value={filterUser}
                onChange={(e) => setFilterUser(e.target.value)}
                className="px-2 py-1 rounded border border-border bg-background text-xs font-mono"
              >
                <option value="">Все</option>
                {uniqueUsers.map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>
            </div>
            {(filterStatus || filterAction || filterUser) && (
              <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => { setFilterStatus(''); setFilterAction(''); setFilterUser(''); }}>
                Сбросить
              </Button>
            )}
          </div>
        )}
        <div className="rounded-sm border border-border bg-black shadow-2xl overflow-hidden h-full flex flex-col relative">

          {/* Timeline Bar — реальное распределение событий по времени */}
          <div className="h-12 border-b border-border bg-muted flex items-end px-4 gap-1 pt-4 overflow-hidden shrink-0 pointer-events-none opacity-50">
            {(() => {
              if (!filteredEvents.length) return Array.from({ length: 120 }).map((_, i) => (
                <div key={i} className="w-1 rounded-t-sm bg-[#222] h-1" />
              ));
              // Собираем 120 бакетов из реальных событий
              const buckets = Array(120).fill(0);
              const statusBuckets: string[][] = Array.from({ length: 120 }, () => []);
              const now = Date.now();
              const range = 24 * 60 * 60 * 1000; // 24 часа
              filteredEvents.forEach(e => {
                const t = new Date(e.timestamp).getTime();
                const idx = Math.floor(((now - t) / range) * 120);
                if (idx >= 0 && idx < 120) {
                  buckets[119 - idx]++;
                  statusBuckets[119 - idx].push(e.status);
                }
              });
              const maxB = Math.max(...buckets, 1);
              return buckets.map((count, i) => {
                const h = count > 0 ? Math.max(4, (count / maxB) * 32) : 1;
                const hasFailed = statusBuckets[i].includes('FAILED');
                const hasWarning = statusBuckets[i].includes('WARNING');
                const color = hasFailed ? 'bg-destructive' : hasWarning ? 'bg-warning' : count > 0 ? 'bg-primary/60' : 'bg-[#222]';
                return <div key={i} className={`w-1 rounded-t-sm ${color}`} style={{ height: `${h}px` }} />;
              });
            })()}
          </div>

          <div className="flex-1 overflow-auto custom-scrollbar relative">
            <table className="w-full min-w-[800px] text-left whitespace-nowrap table-fixed">
              <thead className="bg-[#151515]/80 border-b border-border text-[10px] uppercase font-mono tracking-widest font-bold text-muted-foreground sticky top-0 backdrop-blur-md z-10">
                <tr>
                  <th className="px-4 py-3 w-[180px]">Timestamp</th>
                  <th className="px-4 py-3 w-[120px]">Status</th>
                  <th className="px-4 py-3 w-[250px]">Action</th>
                  <th className="px-4 py-3 w-[200px]">User</th>
                  <th className="px-4 py-3">Resource</th>
                  <th className="px-4 py-3 w-[150px] text-right">Source IP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#222]/50 font-mono text-xs text-foreground/80">
                {filteredEvents.map((event) => (
                  <tr
                    key={event.id}
                    onClick={() => setSelectedEvent(event)}
                    className={`transition-colors group cursor-pointer ${selectedEvent?.id === event.id ? 'bg-primary/10 border-l-2 border-l-primary' : 'hover:bg-[#151515] border-l-2 border-l-transparent'}`}
                  >
                    <td className="px-4 py-3 text-muted-foreground text-[10px]">
                      {new Date(event.timestamp).toLocaleString(undefined, {
                        month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'
                      })}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <StatusIcon status={event.status} />
                        <span className={`text-[9px] font-bold tracking-widest ${event.status === 'SUCCESS' ? 'text-success'
                          : event.status === 'FAILED' ? 'text-destructive'
                            : 'text-warning'
                          }`}>{event.status}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-[11px] font-bold tracking-wider text-primary/80 group-hover:text-primary transition-colors">
                      {event.action}
                    </td>
                    <td className="px-4 py-3 text-foreground truncate">{event.user}</td>
                    <td className="px-4 py-3 text-muted-foreground truncate">{event.resource}</td>
                    <td className="px-4 py-3 text-[#555] text-right">{event.ip}</td>
                  </tr>
                ))}
                {isLoading && (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-muted-foreground animate-pulse">
                      Loading audit logs...
                    </td>
                  </tr>
                )}
                {!isLoading && filteredEvents.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center">
                      <Shield className="w-8 h-8 text-[#333] mx-auto mb-3" />
                      <span className="text-muted-foreground font-mono text-xs uppercase tracking-widest">No audit events match current filters</span>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Slide-out Drawer Panel */}
      <AuditDrawer event={selectedEvent} onClose={() => setSelectedEvent(null)} />

      {/* Backdrop for mobile or smaller screens when drawer is open */}
      {selectedEvent && (
        <div
          className="absolute inset-0 bg-black/50 z-30 transition-opacity xl:hidden"
          onClick={() => setSelectedEvent(null)}
        />
      )}
    </div>
  );
}
