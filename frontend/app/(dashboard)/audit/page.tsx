'use client';
import { useState, useMemo } from 'react';
import { Shield, Filter, AlertTriangle, CheckCircle2, XCircle, Info, Download } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { useAuthStore } from '@/lib/store';
import { AuditQueryBuilder } from '@/src/features/audit/AuditQueryBuilder';
import { AuditDrawer } from '@/src/features/audit/AuditDrawer';

// Mock interface for now, will connect to /api/v1/audit/
interface AuditEvent {
  id: string;
  timestamp: string;
  user: string;
  action: string;
  resource: string;
  status: 'SUCCESS' | 'FAILED' | 'WARNING';
  ip: string;
}

const MOCK_EVENTS: AuditEvent[] = [
  { id: 'EV-8842', timestamp: new Date(Date.now() - 120000).toISOString(), user: 'admin@sphere.local', action: 'LOGIN_ATTEMPT', resource: 'System', status: 'SUCCESS', ip: '10.0.0.45' },
  { id: 'EV-8841', timestamp: new Date(Date.now() - 360000).toISOString(), user: 'operator_1', action: 'EXECUTE_SCRIPT', resource: 'Device Group: EU-Farm', status: 'SUCCESS', ip: '192.168.1.100' },
  { id: 'EV-8840', timestamp: new Date(Date.now() - 8640000).toISOString(), user: 'system', action: 'VPN_TUNNEL_DROP', resource: 'Node-04', status: 'FAILED', ip: '10.8.0.4' },
  { id: 'EV-8839', timestamp: new Date(Date.now() - 12000000).toISOString(), user: 'admin@sphere.local', action: 'UPDATE_CONFIG', resource: 'Settings: Redis', status: 'WARNING', ip: '10.0.0.45' },
  { id: 'EV-8838', timestamp: new Date(Date.now() - 15000000).toISOString(), user: 'operator_2', action: 'DEVICE_REBOOT', resource: 'Node-09', status: 'SUCCESS', ip: '192.168.1.101' },
  { id: 'EV-8837', timestamp: new Date(Date.now() - 25000000).toISOString(), user: 'system', action: 'CRON_JOB_FAILED', resource: 'Task: Backup DB', status: 'FAILED', ip: '127.0.0.1' },
];

export default function AuditLogsPage() {
  const [events, setEvents] = useState<AuditEvent[]>(MOCK_EVENTS);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);

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
    if (!searchQuery.trim()) return events;

    const terms = searchQuery.toLowerCase().split(' ').filter(Boolean);
    return events.filter(e => {
      return terms.every(term => {
        if (term.includes(':')) {
          const [key, val] = term.split(':');
          if (key === 'status') return e.status.toLowerCase() === val;
          if (key === 'action') return e.action.toLowerCase().includes(val);
          if (key === 'user') return e.user.toLowerCase().includes(val);
        }
        // Fallback global search
        return JSON.stringify(e).toLowerCase().includes(term);
      });
    });
  }, [events, searchQuery]);

  return (
    <div className="flex flex-col h-full bg-[#0A0A0A] relative overflow-hidden">

      {/* Header */}
      <div className="px-6 py-5 border-b border-[#222] bg-[#111] flex flex-col md:flex-row md:items-center justify-between gap-4 shrink-0 z-10">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Shield className="w-5 h-5 text-primary" />
            <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">Security Audit</h1>
          </div>
          <p className="text-[10px] text-muted-foreground max-w-xl font-mono uppercase tracking-widest mt-1">
            Immutable log of all user actions, system events, and security access attempts.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <AuditQueryBuilder value={searchQuery} onChange={setSearchQuery} />

          <Button variant="outline" size="sm" className="h-9 border-[#333] hover:bg-[#222]">
            <Filter className="w-4 h-4 mr-2" />
            <span className="text-[10px] uppercase font-bold tracking-widest">Filters</span>
          </Button>
          <Button variant="default" size="sm" className="h-9 bg-primary/20 text-primary hover:bg-primary/30 border border-primary/50">
            <Download className="w-4 h-4 mr-2" />
            <span className="text-[10px] uppercase font-bold tracking-widest">Export CSV</span>
          </Button>
        </div>
      </div>

      {/* Table Area */}
      <div className="flex-1 overflow-auto p-6 relative">
        <div className="rounded-sm border border-[#222] bg-black shadow-2xl overflow-hidden h-full flex flex-col relative">

          {/* Timeline Bar Mock */}
          <div className="h-12 border-b border-[#222] bg-[#111] flex items-end px-4 gap-1 pt-4 overflow-hidden shrink-0 pointer-events-none opacity-50">
            {Array.from({ length: 120 }).map((_, i) => (
              <div key={i} className={`w-1 rounded-t-sm ${Math.random() > 0.9 ? 'bg-destructive h-8' : Math.random() > 0.7 ? 'bg-warning h-4' : 'bg-[#333] h-2'}`} />
            ))}
          </div>

          <div className="flex-1 overflow-auto custom-scrollbar relative">
            <table className="w-full text-left whitespace-nowrap table-fixed">
              <thead className="bg-[#151515]/80 border-b border-[#222] text-[10px] uppercase font-mono tracking-widest font-bold text-muted-foreground sticky top-0 backdrop-blur-md z-10">
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
                {filteredEvents.length === 0 && (
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
