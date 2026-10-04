'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Copy, MousePointer2, RefreshCw, ScanSearch } from 'lucide-react';
import { toast } from 'sonner';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { useAuthStore } from '@/lib/store';
import { useCapabilities, PermissionNotice } from '@/src/features/access/Capabilities';
import { Button } from '@/src/shared/ui/button';
import type { StreamFrameDimensions } from './streamAspectRatio';
import { checkedHierarchy, frameBounds, hitTestHierarchy, matchesFrame, type UiHierarchyNode, type UiHierarchySnapshot } from './uiHierarchy';

const SNAPSHOT_LIFETIME_MS = 30_000;

export function SingleDeviceStream({ deviceId }: { deviceId: string }) {
  const access = useCapabilities();
  const { accessToken } = useAuthStore();
  const canInspect = access.can('device:write');
  const [inspect, setInspect] = useState(false);
  const [frame, setFrame] = useState<StreamFrameDimensions | null>(null);
  const [report, setReport] = useState<{ snapshot: UiHierarchySnapshot; deviceId: string; token: string | null; at: number } | null>(null);
  const [selected, setSelected] = useState<UiHierarchyNode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [now, setNow] = useState(0);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const invalidated = useCallback(() => {
    generation.current++;
    controller.current?.abort();
    controller.current = null;
    setPending(false); setReport(null); setSelected(null);
  }, []);
  const invalidateFrame = useCallback(() => { invalidated(); setFrame(null); }, [invalidated]);
  useEffect(() => { invalidateFrame(); setError(null); }, [deviceId, accessToken, invalidateFrame]);
  useEffect(() => { if (!canInspect) { invalidated(); setError(null); } }, [canInspect, invalidated]);
  useEffect(() => () => { generation.current++; controller.current?.abort(); }, []);
  useEffect(() => {
    if (!inspect) return;
    const timer = window.setInterval(() => setNow(performance.now()), 1000);
    return () => window.clearInterval(timer);
  }, [inspect]);
  const snapshot = canInspect && report?.deviceId === deviceId && report.token === accessToken ? report.snapshot : null;
  const age = report ? Math.max(0, now - report.at) : Infinity;
  const valid = snapshot && matchesFrame(snapshot, frame) && age < SNAPSHOT_LIFETIME_MS;
  const refresh = async () => {
    if (!canInspect || !inspect || !frame || controller.current) return;
    const request = new AbortController();
    controller.current = request;
    const ownGeneration = ++generation.current;
    const requestedAt = performance.now();
    setPending(true); setError(null); setSelected(null); setReport(null);
    try {
      const { data } = await api.post(`/devices/${encodeURIComponent(deviceId)}/ui-hierarchy`, undefined,
        { signal: request.signal, timeout: 50_000 });
      const next = checkedHierarchy(data, deviceId);
      if (ownGeneration !== generation.current || request.signal.aborted) return;
      // Start the lease before the request; WAN/cleanup time cannot make an
      // old Android tree appear freshly captured on arrival.
      setReport({ snapshot: next, deviceId, token: accessToken, at: requestedAt }); setNow(performance.now());
    } catch (reason) {
      if (ownGeneration === generation.current && !request.signal.aborted) setError(getApiErrorMessage(reason,
        reason instanceof Error ? reason.message : 'Не удалось прочитать дерево Android.'));
    } finally {
      if (ownGeneration === generation.current) { controller.current = null; setPending(false); }
    }
  };
  const pick = (x: number, y: number, dimensions: StreamFrameDimensions) => {
    if (!valid || !snapshot || !matchesFrame(snapshot, dimensions)) return;
    setSelected(hitTestHierarchy(snapshot, x * snapshot.width / dimensions.width, y * snapshot.height / dimensions.height));
  };
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); toast.success('Скопировано'); }
    catch { toast.error('Не удалось скопировать'); }
  };
  const highlight = valid && selected?.bounds && snapshot && frame ? frameBounds(selected.bounds, snapshot, frame) : null;
  return <section className="min-w-0 space-y-3" aria-label="Видеопоток и инспектор Android">
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-card p-3">
      <div className="flex flex-wrap gap-2">
        <Button variant={inspect ? 'outline' : 'default'} size="sm" aria-pressed={!inspect} onClick={() => { setInspect(false); invalidated(); }}><MousePointer2 className="mr-2 h-4 w-4" aria-hidden />Управление</Button>
        <Button variant={inspect ? 'default' : 'outline'} size="sm" disabled={!canInspect} aria-pressed={inspect} onClick={() => { invalidated(); setInspect(true); setError(null); }}><ScanSearch className="mr-2 h-4 w-4" aria-hidden />XPath-инспектор</Button>
      </div>
      {inspect && <Button variant="outline" size="sm" disabled={!canInspect || !frame || pending} onClick={() => { void refresh(); }}><RefreshCw className={`mr-2 h-4 w-4 ${pending ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden />{pending ? 'Читаем дерево…' : 'Обновить дерево'}</Button>}
    </div>
    {!canInspect && <PermissionNotice permission="device:write" action="чтение дерева Android через root-команды" />}
    <div className={inspect ? 'grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]' : 'min-w-0'}>
      <div className="min-w-0 overflow-hidden rounded-xl border border-border bg-black">
        <DeviceStream deviceId={deviceId} enableDiagnostics enableScreenshot enableNavigation enableStaticInput
          readOnly={!access.can('stream:control')} onFrameDimensions={setFrame} onInspectionInvalidated={invalidateFrame}
          inspection={inspect ? { onPick: pick, bounds: highlight } : undefined} />
      </div>
      {inspect && <aside className="min-w-0 space-y-4 rounded-xl border border-border bg-card p-4" aria-label="Элемент Android">
        <div><h4 className="font-semibold">Инспектор элементов</h4><p className="mt-1 text-xs leading-relaxed text-muted-foreground">Выбор на экране не отправляет нажатие Android. Дерево читается вручную через APK; для этого требуется root и UI Automator.</p></div>
        <p className="text-xs leading-relaxed text-muted-foreground">Дерево и видео получаются независимо. После изменения экрана обновите дерево. Игровой Canvas может не предоставлять внутренних элементов.</p>
        {error && <p role="alert" className="break-words rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
        {pending ? <p role="status" className="text-sm">Ожидаем полный снимок, до 50 секунд. Повтор не отправляется автоматически.</p>
          : !snapshot ? <p role="status" className="text-sm text-muted-foreground">Нажмите «Обновить дерево» после появления видеокадра.</p>
            : <div className="space-y-2 text-xs text-muted-foreground"><p>{snapshot.width} × {snapshot.height} · поворот {snapshot.rotation * 90}° · {snapshot.nodes.length} элементов</p><p>Получено: {new Date(snapshot.completed_at).toLocaleTimeString('ru-RU')} · {Math.floor(age / 1000)} с назад</p>
              {!snapshot.temporary_file_cleanup_confirmed && <p role="status" className="text-amber-600 dark:text-amber-400">Удаление временного файла дерева не подтверждено. Проверьте связь и логи APK.</p>}
              {!valid && <p role="status" className="text-amber-600 dark:text-amber-400">{matchesFrame(snapshot, frame) ? 'Снимок устарел. Обновите дерево.' : 'Геометрия дерева не совпадает с видео. Обновите дерево после поворота.'}</p>}
              {snapshot.nodes.length === 0 && <p>Android не предоставил элементов для текущего окна.</p>}
            </div>}
        {valid && selected ? <div className="min-w-0 space-y-3">
          <div className="flex items-center justify-between gap-2"><h5 className="text-sm font-semibold">Узел #{selected.id} · глубина {selected.depth}</h5><Button size="sm" variant="ghost" aria-label="Копировать атрибуты элемента" onClick={() => { void copy(JSON.stringify(selected, null, 2)); }}><Copy className="h-4 w-4" aria-hidden /></Button></div>
          <div className="rounded-lg bg-muted p-3"><p className="text-xs font-medium">XPath</p><code className="mt-1 block break-all text-xs">{selected.xpath}</code><Button size="sm" variant="outline" className="mt-2" onClick={() => { void copy(selected.xpath); }}>Копировать XPath</Button></div>
          <dl className="max-h-[min(60vh,640px)] space-y-2 overflow-auto text-xs">{Object.entries(selected.attributes).map(([key, value]) => <div key={key} className="border-b border-border pb-2"><dt className="font-medium text-muted-foreground">{key}</dt><dd className="mt-1 whitespace-pre-wrap break-all font-mono">{value || 'Пустое значение'}</dd></div>)}</dl>
        </div> : valid && snapshot.nodes.length > 0 && <p className="text-sm text-muted-foreground">Выберите элемент на изображении. Если границы не найдены, Android не раскрыл элемент в этой точке.</p>}
      </aside>}
    </div>
  </section>;
}
