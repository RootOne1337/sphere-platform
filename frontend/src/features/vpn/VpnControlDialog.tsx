'use client';
import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/lib/store';
import { useVpnKillSwitch, useVpnRotate } from '@/lib/hooks/useVpn';
import { useBulkAction } from '@/lib/hooks/useDevices';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { controlFailure, controlReceipt, type ControlOutcome, type VpnControl } from './controlReceipt';

export const vpnActorScope = () => {
  const s = useAuthStore.getState();
  return `${s.user?.org_id}:${s.user?.id}:${s.user?.role}:${s.sessionVersion}`;
};
const titles: Record<VpnControl, string> = { rotate: 'Ротация VPN IP', enable: 'Включить kill switch', disable: 'Выключить kill switch', reboot: 'Перезагрузить устройство' };

export function VpnControlDialog({ kind, ids, scope, fresh, reload, onOutcomes, onClose }: {
  kind: VpnControl; ids: string[]; scope: string; fresh: boolean;
  reload: () => Promise<boolean>; onOutcomes: (rows: ControlOutcome[]) => void; onClose: () => void;
}) {
  const rotate = useVpnRotate(); const kill = useVpnKillSwitch(); const reboot = useBulkAction();
  const [pending, setPending] = useState(false); const [done, setDone] = useState(false);
  const [confirmed, setConfirmed] = useState(false); const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<ControlOutcome[]>([]); const [retryIds, setRetryIds] = useState<string[] | null>(null);
  const busy = useRef(false); const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const targets = retryIds ?? ids;
  async function submit() {
    if (busy.current || done || !confirmed || !fresh || scope !== vpnActorScope() || !targets.length || targets.length > 500 || new Set(targets).size !== targets.length) return;
    busy.current = true; setPending(true); setError(null);
    let dispatched = false;
    try {
      if (!(await reload()) || scope !== vpnActorScope() || !live.current) throw new Error('Catalog not confirmed');
      dispatched = true;
      const response = kind === 'rotate' ? (await rotate.mutateAsync({ device_ids: targets })).data
        : kind === 'reboot' ? await reboot.mutateAsync({ device_ids: targets, action: 'reboot' })
          : (await kill.mutateAsync({ device_ids: targets, enabled: kind === 'enable' })).data;
      if (!live.current || scope !== vpnActorScope()) return;
      const receipt = controlReceipt(kind, response, targets);
      setRows(receipt); setDone(true); setConfirmed(false); onOutcomes(receipt);
    } catch (failure) {
      if (!live.current || scope !== vpnActorScope()) return;
      const result = dispatched ? controlFailure(failure) : { unknown: false, message: 'Каталог не подтверждён. Команда не отправлялась.' };
      setError(result.message); setDone(true); setConfirmed(false);
      if (result.unknown) {
        const unknown = targets.map(deviceId => ({ deviceId, outcome: 'unknown', detail: result.message, retryable: false }));
        setRows(unknown); onOutcomes(unknown);
      }
    } finally { busy.current = false; if (live.current) setPending(false); }
  }
  return <Dialog open onOpenChange={open => { if (!open && !busy.current) onClose(); }}>
    <DialogContent className="max-h-[85dvh] max-w-2xl overflow-y-auto">
      <DialogHeader><DialogTitle>{titles[kind]}</DialogTitle><DialogDescription>Явный список устройств и результат по каждой цели. Отправка команды не означает завершение действия Android.</DialogDescription></DialogHeader>
      <p className="rounded-lg border border-warning/40 p-3 text-sm">{kind === 'rotate' ? 'Прежний VPN peer будет отозван. Если новое назначение не завершится, связь через VPN может пропасть.'
        : kind === 'enable' ? 'Блокировка сетевого трафика может отключить удалённый доступ. Текущий legacy transport этой операции не подключён.'
          : kind === 'disable' ? 'После отключения блокировки трафик может идти вне VPN. Текущий legacy transport этой операции не подключён.'
            : 'Перезагрузка прервёт стрим и задания. Получение команды не подтверждает последующий запуск Android.'}</p>
      <p className="text-sm">Выбрано: {targets.length} устройств</p><ul className="max-h-40 space-y-1 overflow-y-auto rounded-lg border p-3 text-xs">{targets.map(id => <li key={id} className="break-all font-mono">{id}</li>)}</ul>
      {!fresh && <p role="alert">Каталог обновляется или недоступен. Отправка заблокирована.</p>}
      {error && <p role="alert" className="rounded-lg border border-destructive/40 p-3 text-sm">{error}</p>}
      {rows.length > 0 && <section aria-label="Результаты операции" className="space-y-3">{rows.map(row => <article key={row.deviceId} className="rounded-lg border p-3 text-sm"><p className="break-all font-mono text-xs">{row.deviceId}</p><p className="mt-1 font-semibold">{row.outcome}</p><p className="mt-1">{row.detail}</p></article>)}</section>}
      {!done && <><label className="flex items-start gap-3 text-sm"><input type="checkbox" checked={confirmed} disabled={pending} onChange={e => setConfirmed(e.target.checked)} />Понимаю последствия для выбранных устройств</label><Button variant="destructive" disabled={pending || !confirmed || !fresh || !targets.length || targets.length > 500} onClick={() => { void submit(); }}>{pending ? 'Проверка и отправка…' : 'Подтвердить операцию'}</Button></>}
      {done && rows.some(v => v.retryable) && <Button variant="outline" disabled={pending || !fresh} onClick={() => { setRetryIds(rows.filter(v => v.retryable).map(v => v.deviceId)); setDone(false); setConfirmed(false); setError(null); }}>Подготовить повтор только неотправленных</Button>}
      <Button variant="outline" disabled={pending} onClick={onClose}>Закрыть результаты</Button>
    </DialogContent>
  </Dialog>;
}
