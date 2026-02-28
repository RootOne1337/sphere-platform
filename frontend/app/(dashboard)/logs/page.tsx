'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import { useDevices } from '@/lib/hooks/useDevices';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

// ── Types ─────────────────────────────────────────────────────────────────────

type LogLevel = 'V' | 'D' | 'I' | 'W' | 'E' | 'A' | 'ALL';

interface LogEntry {
  raw: string;
  level: LogLevel;
  timestamp: string;
  tag: string;
  message: string;
}

interface LogsResponse {
  device_id: string;
  lines: string[];
  total: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const LOG_LEVEL_COLORS: Record<LogLevel, string> = {
  V: 'text-gray-400',
  D: 'text-blue-400',
  I: 'text-green-400',
  W: 'text-yellow-400',
  E: 'text-red-400',
  A: 'text-red-600 font-bold',
  ALL: 'text-gray-300',
};

// Parse "2026-02-23T10:15:30.123 D/Tag: message"
const LOG_PATTERN = /^(\S+T\S+)\s+([VDIEA])\/([^:]+):\s(.*)$/;

function parseLine(raw: string): LogEntry {
  const m = raw.match(LOG_PATTERN);
  if (m) {
    return { raw, level: m[2] as LogLevel, timestamp: m[1], tag: m[3].trim(), message: m[4] };
  }
  // Fallback: try to detect level from logcat threadtime format
  const levelMatch = raw.match(/\s([VDIWEAF])\/\S/);
  return {
    raw,
    level: (levelMatch?.[1] as LogLevel) ?? 'ALL',
    timestamp: '',
    tag: '',
    message: raw,
  };
}

// ── Page Component ────────────────────────────────────────────────────────────

export default function LogsPage() {
  const { data: devicesData } = useDevices({});
  const devices = devicesData?.items ?? [];

  const [selectedDevice, setSelectedDevice] = useState<string>('');
  const [search, setSearch] = useState('');
  const [levelFilter, setLevelFilter] = useState<LogLevel>('ALL');
  const [lines, setLines] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [totalLines, setTotalLines] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const fetchLogs = useCallback(async (deviceId: string, scrollToBottom = false) => {
    if (!deviceId) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ lines: '1000' });
      if (search) params.set('search', search);
      const { data } = await api.get(`/logs/${deviceId}?${params}`);
      const parsed = data.lines.map(parseLine);
      setLines(parsed);
      setTotalLines(data.total);
      if (scrollToBottom) {
        setTimeout(() => {
          containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight });
        }, 50);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load logs');
    } finally {
      setLoading(false);
    }
  }, [search]);

  // Auto-refresh
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (autoRefresh && selectedDevice) {
      intervalRef.current = setInterval(() => fetchLogs(selectedDevice, true), 5000);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [autoRefresh, selectedDevice, fetchLogs]);

  // Fetch on device/search change
  useEffect(() => {
    if (selectedDevice) fetchLogs(selectedDevice, true);
  }, [selectedDevice, fetchLogs]);

  // Auto-select first device
  useEffect(() => {
    if (!selectedDevice && devices.length > 0) setSelectedDevice(devices[0].id);
  }, [devices, selectedDevice]);

  const filteredLines = levelFilter === 'ALL'
    ? lines
    : lines.filter((ln) => ln.level === levelFilter);

  const handleClear = async () => {
    if (!selectedDevice) return;
    if (!confirm('Clear all logs for this device?')) return;
    await api.delete(`/logs/${selectedDevice}`);
    setLines([]);
    setTotalLines(0);
  };

  return (
    <div className="flex flex-col h-full gap-4">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Device Logs</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Real-time agent logs from enrolled devices
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant={autoRefresh ? 'default' : 'outline'}
            size="sm"
            onClick={() => setAutoRefresh((v) => !v)}
          >
            {autoRefresh ? '⏸ Pause' : '▶ Auto-refresh'}
          </Button>
          <Button variant="outline" size="sm" onClick={handleClear} disabled={!selectedDevice}>
            Clear Logs
          </Button>
        </div>
      </div>

      {/* ── Filters ── */}
      <div className="flex flex-wrap gap-3 items-center">
        <Select value={selectedDevice} onValueChange={setSelectedDevice}>
          <SelectTrigger className="w-[220px]">
            <SelectValue placeholder="Select device…" />
          </SelectTrigger>
          <SelectContent>
            {devices.map((d) => (
              <SelectItem key={d.id} value={d.id}>
                {d.name} ({d.id.slice(0, 8)}…)
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={levelFilter} onValueChange={(v) => setLevelFilter(v as LogLevel)}>
          <SelectTrigger className="w-[130px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(['ALL', 'V', 'D', 'I', 'W', 'E', 'A'] as LogLevel[]).map((lvl) => (
              <SelectItem key={lvl} value={lvl}>
                {lvl === 'ALL' ? 'All levels' : lvl === 'V' ? 'Verbose'
                  : lvl === 'D' ? 'Debug' : lvl === 'I' ? 'Info'
                  : lvl === 'W' ? 'Warning' : lvl === 'E' ? 'Error' : 'Assert'}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Input
          className="w-[240px]"
          placeholder="Search logs…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <Badge variant="outline" className="ml-auto">
          {filteredLines.length}/{totalLines} lines
        </Badge>
      </div>

      {/* ── Log viewer ── */}
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto rounded-lg border bg-black font-mono text-xs p-3 min-h-[400px] max-h-[calc(100vh-280px)]"
      >
        {error && (
          <div className="text-red-400 p-2">Error: {error}</div>
        )}
        {loading && lines.length === 0 && (
          <div className="text-gray-500 p-2">Loading logs…</div>
        )}
        {!loading && !error && lines.length === 0 && selectedDevice && (
          <div className="text-gray-500 p-2">No logs found for this device yet.</div>
        )}
        {!selectedDevice && (
          <div className="text-gray-500 p-2">Select a device to view logs.</div>
        )}
        {filteredLines.map((entry, i) => (
          <div key={i} className={`leading-5 whitespace-pre-wrap break-all ${LOG_LEVEL_COLORS[entry.level]}`}>
            {entry.timestamp
              ? <><span className="text-gray-500">{entry.timestamp}</span>{' '}<span className="font-bold">{entry.level}/{entry.tag}:</span>{' '}{entry.message}</>
              : entry.raw
            }
          </div>
        ))}
      </div>
    </div>
  );
}
