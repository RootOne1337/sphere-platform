'use client';
import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { AUDIT_EXPORT_LIMIT, auditExportReceipt, downloadAuditCsv, type AuditFilters, type AuditExportReceipt } from './investigation';

export function useAuditExport() {
  const active = useRef<AbortController | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [receipt, setReceipt] = useState<AuditExportReceipt | null>(null);
  const [cancelled, setCancelled] = useState(false);
  useEffect(() => () => { active.current?.abort(); active.current = null; }, []);
  function cancel() {
    active.current?.abort(); active.current = null;
    setPending(false); setReceipt(null); setError(''); setCancelled(true);
  }
  async function run(filters: AuditFilters) {
    if (active.current) return;
    const controller = new AbortController(); active.current = controller;
    setPending(true); setError(''); setReceipt(null); setCancelled(false);
    try {
      const response = await api.get<Blob>('/audit/logs/export', {
        params: { ...filters, limit: AUDIT_EXPORT_LIMIT }, responseType: 'blob', signal: controller.signal,
      });
      if (controller.signal.aborted || active.current !== controller) return;
      const confirmed = auditExportReceipt(response.data, response.headers);
      downloadAuditCsv(response.data, confirmed); setReceipt(confirmed);
    } catch (failure) {
      if (controller.signal.aborted || active.current !== controller) return;
      const status = (failure as { response?: { status?: number } })?.response?.status;
      setError(status === 401 || status === 403 ? 'Экспорт недоступен: проверьте доступ audit:read.'
        : 'Не удалось подтвердить экспорт CSV. Файл не скачан; повторите запрос или уточните фильтры.');
    } finally {
      if (active.current === controller) { active.current = null; setPending(false); }
    }
  }
  return { run, cancel, pending, error, receipt, cancelled };
}
