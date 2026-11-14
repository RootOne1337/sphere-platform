'use client';

import { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { getApiErrorMessage } from '@/lib/apiError';
import { Button } from '@/src/shared/ui/button';
import { DEVICE_COMMAND_TIMEOUT, interactiveResult } from './interactiveResult';
import { utcTime } from './DeviceOperationsPanels';

const SOURCES = [
  { id: 'properties', label: 'Android и идентификаторы', command: 'getprop' },
  { id: 'cpu', label: 'CPU, видимый Android', command: 'cat /proc/cpuinfo' },
  { id: 'memory', label: 'Память Android, kB', command: 'cat /proc/meminfo' },
  { id: 'display', label: 'Разрешение Android', command: 'wm size' },
  { id: 'density', label: 'Плотность экрана', command: 'wm density' },
  { id: 'network', label: 'Интерфейсы и адреса Android', command: 'ip -o addr show' },
  { id: 'uptime', label: 'Время работы Android, секунды', command: 'cat /proc/uptime' },
] as const;
type Source = (typeof SOURCES)[number];
type Row = { key: string; value: string };
type Report = { source: Source; rows: Row[]; observedAt: string; elapsedMs: number; error?: string };

export function parseAndroidProfile(id: Source['id'], output: string): Row[] {
  if (!output || output.length > 128 * 1024 || /\u0000/.test(output)) throw new Error('Android вернул пустой или слишком большой ответ.');
  const lines = output.trim().split(/\r?\n/);
  if (lines.length > 1024 || lines.some(line => line.length > 4096)) throw new Error('Ответ Android превышает пределы профиля.');
  let rows: Row[];
  if (id === 'properties') {
    rows = lines.flatMap(line => {
      const match = /^\[([a-zA-Z0-9._-]+)\]: \[(.*)\]$/.exec(line);
      if (!match) return [];
      // Device/system identity only; arbitrary app/vendor properties may
      // contain credentials and do not belong in this profile or telemetry.
      const key = match[1];
      if (!/^(ro\.product\.|ro\.soc\.|ro\.build\.version\.|ro\.build\.fingerprint$|ro\.hardware$|ro\.boot\.hardware$|ro\.(boot\.)?serialno$|ro\.kernel\.qemu$|ro\.secure$|ro\.debuggable$)/.test(key)) return [];
      return [{ key, value: match[2] || 'Не сообщено' }];
    });
  } else if (id === 'cpu' || id === 'memory' || id === 'display' || id === 'density') {
    rows = lines.flatMap(line => {
      const index = line.indexOf(':');
      return index > 0 ? [{ key: line.slice(0, index).trim(), value: line.slice(index + 1).trim() }] : [];
    });
    if (id === 'cpu' && !rows.some(row => /^(processor|model name|Hardware|CPU architecture)$/i.test(row.key))) rows = [];
    if (id === 'memory' && !rows.some(row => row.key === 'MemTotal' && /^\d+ kB$/.test(row.value))) rows = [];
    if (id === 'display' && !rows.some(row => /^(Physical|Override) size$/.test(row.key) && /^\d+x\d+$/.test(row.value))) rows = [];
    if (id === 'density' && !rows.some(row => /^(Physical|Override) density$/.test(row.key) && /^\d+$/.test(row.value))) rows = [];
  } else if (id === 'network') {
    rows = lines.flatMap(line => {
      const match = /^\d+:\s+(\S+)\s+(inet6?)\s+(\S+)/.exec(line);
      return match ? [{ key: `${match[1]} · ${match[2]}`, value: match[3] }] : [];
    });
  } else {
    const match = /^(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)$/.exec(output.trim());
    rows = match ? [{ key: 'Uptime', value: match[1] }, { key: 'Суммарный idle CPU', value: match[2] }] : [];
  }
  if (!rows.length || rows.length > 512) throw new Error('Android не вернул распознаваемые сведения для этого раздела.');
  return rows;
}

export function AndroidProfilePanel({ deviceId, enabled }: { deviceId: string; enabled: boolean }) {
  const { accessToken } = useAuthStore();
  const [reports, setReports] = useState<Report[]>([]);
  const [pending, setPending] = useState(false);
  const enabledRef = useRef(enabled); enabledRef.current = enabled;
  const sessionRef = useRef<{ disposed: boolean; controller: AbortController | null } | null>(null);
  useEffect(() => {
    const session = { disposed: false, controller: null as AbortController | null };
    sessionRef.current = session; setReports([]); setPending(false);
    return () => { session.disposed = true; session.controller?.abort(); if (sessionRef.current === session) sessionRef.current = null; };
  }, [deviceId, accessToken]);
  const read = async () => {
    const session = sessionRef.current;
    if (!enabledRef.current || !session || session.disposed || session.controller) return;
    const controller = new AbortController(); session.controller = controller;
    const deadline = window.setTimeout(() => controller.abort(), 60_000);
    setPending(true); setReports([]);
    try {
      for (const source of SOURCES) {
        if (session.disposed || sessionRef.current !== session || !enabledRef.current || controller.signal.aborted) break;
        const start = performance.now();
        let report: Report;
        try {
          const { data } = await api.post(`/devices/${encodeURIComponent(deviceId)}/shell`, { command: source.command }, {
            signal: controller.signal, timeout: DEVICE_COMMAND_TIMEOUT.shell,
          });
          report = { source, rows: parseAndroidProfile(source.id, interactiveResult(data, 'output')), observedAt: new Date().toISOString(), elapsedMs: Math.round(performance.now() - start) };
        } catch (failure) {
          report = { source, rows: [], observedAt: new Date().toISOString(), elapsedMs: Math.round(performance.now() - start), error: getApiErrorMessage(failure, failure instanceof Error ? failure.message : 'Нет результата Android.').slice(0, 500) };
        }
        if (session.disposed || sessionRef.current !== session) break;
        setReports(old => [...old, report]);
        if (report.error) break; // Stop at the first failure; no WAN retry storm.
      }
    } finally {
      window.clearTimeout(deadline);
      if (!session.disposed && sessionRef.current === session) { session.controller = null; setPending(false); }
    }
  };
  return <section aria-label="Профиль Android" className="min-w-0 space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div className="space-y-1"><h4 className="font-semibold">Профиль Android</h4><p className="text-sm text-muted-foreground">Системные сведения из APK выбранного устройства.</p></div><Button variant="outline" disabled={!enabled || pending} onClick={() => { void read(); }}><RefreshCw className={`mr-2 h-4 w-4 ${pending ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden />Прочитать Android</Button></div>
    <p className="rounded-xl border border-border bg-muted/20 p-3 text-xs leading-relaxed text-muted-foreground">Показывается Android-гость: его виртуальное железо и интерфейсы, а не физический ПК. Серийники могут совпадать у клонов и не доказывают уникальность. Адрес интерфейса не является проверенным внешним IP или IP выхода VPN. Разовый root-запрос, без фонового опроса.</p>
    {pending && <p role="status" className="text-sm text-muted-foreground">Читаем раздел {Math.min(reports.length + 1, SOURCES.length)} из {SOURCES.length}…</p>}
    {!pending && reports.length > 0 && <p role="status" className="text-sm text-muted-foreground">Получено {reports.filter(report => !report.error).length} из {SOURCES.length} разделов.{reports.some(report => report.error) ? ' Чтение остановлено после ошибки; автоповтора нет.' : reports.length < SOURCES.length ? ' Чтение прервано: проверьте связь с Android.' : ' Каждый раздел имеет своё время получения.'}</p>}
    <div className="space-y-3">{reports.map(report => <details key={report.source.id} open={report.source.id === 'properties' || !!report.error} className="overflow-hidden rounded-xl border border-border bg-card"><summary className="cursor-pointer px-4 py-3 text-sm font-medium">{report.source.label} <span className="text-xs font-normal text-muted-foreground">· {report.rows.length} полей · {report.elapsedMs} мс</span></summary><div className="border-t border-border p-4"><p className="mb-3 text-xs text-muted-foreground">{utcTime(report.observedAt)} · {report.source.command}</p>{report.error ? <p role="alert" className="break-words text-sm text-destructive">{report.error}</p> : <dl className="divide-y divide-border">{report.rows.map((row, index) => <div key={index} className="grid min-w-0 grid-cols-1 gap-1 py-2 text-xs sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] sm:gap-3"><dt className="break-all font-mono text-muted-foreground">{row.key}</dt><dd className="min-w-0 whitespace-pre-wrap break-all">{row.value}</dd></div>)}</dl>}</div></details>)}</div>
  </section>;
}
