'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface AuditLog {
  id: string;
  created_at: string;
  user_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  ip_address: string | null;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
}

interface AuditResponse {
  items: AuditLog[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export default function AuditPage() {
  const [page, setPage] = useState(1);
  const [actionFilter, setActionFilter] = useState('');

  const { data, isLoading } = useQuery<AuditResponse>({
    queryKey: ['audit-logs', page, actionFilter],
    queryFn: async () => {
      const params: Record<string, unknown> = { page, per_page: 50 };
      if (actionFilter) params.action = actionFilter;
      const { data } = await api.get('/audit-logs', { params });
      return data;
    },
  });

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Audit Log</h1>
        <Input
          placeholder="Filter by action…"
          value={actionFilter}
          onChange={(e) => { setActionFilter(e.target.value); setPage(1); }}
          className="w-64"
        />
      </div>

      {isLoading ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <>
          <div className="rounded border overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="p-3">Time</th>
                  <th className="p-3">Action</th>
                  <th className="p-3">Resource</th>
                  <th className="p-3">User</th>
                  <th className="p-3">IP</th>
                  <th className="p-3">Changes</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((log) => (
                  <tr key={log.id} className="border-b hover:bg-accent/50">
                    <td className="p-3 text-xs whitespace-nowrap">
                      {new Date(log.created_at).toLocaleString()}
                    </td>
                    <td className="p-3">
                      <Badge variant="outline">{log.action}</Badge>
                    </td>
                    <td className="p-3 text-xs">
                      {log.resource_type && (
                        <span>
                          {log.resource_type}
                          {log.resource_id && <span className="text-muted-foreground"> / {log.resource_id.slice(0, 8)}…</span>}
                        </span>
                      )}
                    </td>
                    <td className="p-3 font-mono text-xs">
                      {log.user_id ? log.user_id.slice(0, 8) + '…' : '—'}
                    </td>
                    <td className="p-3 text-xs text-muted-foreground">{log.ip_address ?? '—'}</td>
                    <td className="p-3 text-xs">
                      {log.new_value && (
                        <code className="text-green-400">
                          {JSON.stringify(log.new_value).slice(0, 60)}
                        </code>
                      )}
                    </td>
                  </tr>
                ))}
                {data?.items.length === 0 && (
                  <tr>
                    <td colSpan={6} className="p-6 text-center text-muted-foreground">
                      No audit logs found
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
              <span className="text-sm text-muted-foreground">{page} / {data.pages}</span>
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
