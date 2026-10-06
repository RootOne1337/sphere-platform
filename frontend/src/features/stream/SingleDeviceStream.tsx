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
import { NativeScreenshotPanel } from '@/src/features/devices/NativeScreenshotPanel';
import type { StreamFrameDimensions } from './streamAspectRatio';
import { checkedHierarchy, frameBounds, hitTestHierarchy, matchesFrame, type UiHierarchyNode, type UiHierarchySnapshot } from './uiHierarchy';
import type { AcknowledgedControl, StreamInput } from './controlObservation';

const SNAPSHOT_LIFETIME_MS = 30_000;

export function SingleDeviceStream({ deviceId, captureEnabled = false, onControlSent, onControlCommand, onInsertSelector, controlDisabled = false, compact = false }: { deviceId: string; captureEnabled?: boolean; controlDisabled?: boolean; compact?: boolean;
  onControlSent?: (input: StreamInput) => void; onControlCommand?: (event: AcknowledgedControl) => void; onInsertSelector?: (node: UiHierarchyNode, snapshot: UiHierarchySnapshot) => void }) {
  const access = useCapabilities();
  const { accessToken } = useAuthStore();
  const canInspect = access.can('device:write');
  const [inspect, setInspect] = useState(false);
  const [automatic, setAutomatic] = useState(true);
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || document.visibilityState !== 'hidden');
  const [frameReport, setFrameReport] = useState<{ dimensions: StreamFrameDimensions; deviceId: string; token: string | null } | null>(null);
  const frame = frameReport?.deviceId === deviceId && frameReport.token === accessToken ? frameReport.dimensions : null;
  const [report, setReport] = useState<{ snapshot: UiHierarchySnapshot; deviceId: string; token: string | null; at: number } | null>(null);
  const [selected, setSelected] = useState<UiHierarchyNode | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [showTree, setShowTree] = useState(false);
  const [treeLimit, setTreeLimit] = useState(200);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [now, setNow] = useState(0);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const selectedRef = useRef<UiHierarchyNode | null>(null);
  const pendingPick = useRef<{ x: number; y: number; dimensions: StreamFrameDimensions } | null>(null);
  const select = useCallback((node: UiHierarchyNode | null) => { selectedRef.current = node; setSelected(node); }, []);
  const onFrame = useCallback((dimensions: StreamFrameDimensions) => {
    setFrameReport({ dimensions, deviceId, token: accessToken });
  }, [deviceId, accessToken]);
  const invalidated = useCallback(() => {
    generation.current++;
    controller.current?.abort();
    controller.current = null;
    pendingPick.current = null;
    setPending(false); setReport(null); select(null); setFeedback(null);
  }, [select]);
  const invalidateFrame = useCallback(() => { invalidated(); setFrameReport(null); }, [invalidated]);
  useEffect(() => { invalidateFrame(); setError(null); }, [deviceId, accessToken, invalidateFrame]);
  useEffect(() => { if (!canInspect) { invalidated(); setError(null); } }, [canInspect, invalidated]);
  useEffect(() => () => { generation.current++; controller.current?.abort(); }, []);
  useEffect(() => {
    const changed = () => setVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', changed);
    return () => document.removeEventListener('visibilitychange', changed);
  }, []);
  useEffect(() => {
    if (!inspect) return;
    const timer = window.setInterval(() => setNow(performance.now()), 1000);
    return () => window.clearInterval(timer);
  }, [inspect]);
  const snapshot = canInspect && report?.deviceId === deviceId && report.token === accessToken ? report.snapshot : null;
  const age = report ? Math.max(0, now - report.at) : Infinity;
  const valid = snapshot && matchesFrame(snapshot, frame) && age < SNAPSHOT_LIFETIME_MS;
  const refresh = useCallback(async () => {
    if (!canInspect || !inspect || !frame || controller.current || document.visibilityState === 'hidden') return;
    const request = new AbortController();
    controller.current = request;
    const ownGeneration = ++generation.current;
    const requestedAt = performance.now();
    // Keep a still-valid tree/selection visible while updating. A new snapshot
    // must revalidate the selected node; positions alone are not identities.
    setPending(true); setError(null);
    try {
      const { data } = await api.post(`/devices/${encodeURIComponent(deviceId)}/ui-hierarchy`, undefined,
        { signal: request.signal, timeout: 50_000 });
      const next = checkedHierarchy(data, deviceId);
      if (ownGeneration !== generation.current || request.signal.aborted) return;
      // Start the lease before the request; WAN/cleanup time cannot make an
      // old Android tree appear freshly captured on arrival.
      setReport({ snapshot: next, deviceId, token: accessToken, at: requestedAt }); setNow(performance.now());
      const queued = pendingPick.current;
      pendingPick.current = null;
      if (performance.now() - requestedAt >= SNAPSHOT_LIFETIME_MS || !matchesFrame(next, frame)) {
        select(null);
      } else if (queued && matchesFrame(next, queued.dimensions)) {
        const node = hitTestHierarchy(next, queued.x * next.width / queued.dimensions.width, queued.y * next.height / queued.dimensions.height);
        select(node);
        setFeedback(node ? null : 'Android не предоставил узел в выбранной точке. Проверьте дерево: игровой Canvas может раскрывать только всю поверхность.');
      } else if (selectedRef.current) {
        const previous = selectedRef.current;
        const node = next.nodes.find(item => item.xpath === previous.xpath
          && item.attributes.class === previous.attributes.class
          && item.attributes['resource-id'] === previous.attributes['resource-id']) ?? null;
        select(node);
        if (!node) setFeedback('Выбранный узел изменился или исчез. Выберите элемент заново.');
      }
    } catch (reason) {
      if (ownGeneration === generation.current && !request.signal.aborted) {
        setError(getApiErrorMessage(reason, reason instanceof Error ? reason.message : 'Не удалось прочитать дерево Android.'));
        setAutomatic(false); pendingPick.current = null;
      }
    } finally {
      if (ownGeneration === generation.current) { controller.current = null; setPending(false); }
    }
  }, [canInspect, inspect, frame, deviceId, accessToken, select]);
  // Mode entry, a new owned picture, or return to this visible page initiates
  // one read. Failed reads pause periodic updates instead of retrying root RPCs.
  useEffect(() => { if (inspect && visible) void refresh(); }, [inspect, visible, refresh]);
  useEffect(() => {
    if (!inspect || !automatic || !visible || !canInspect || !frame || pending || error) return;
    const timer = window.setTimeout(() => { void refresh(); }, 5_000);
    return () => window.clearTimeout(timer);
  }, [inspect, automatic, visible, canInspect, frame, pending, error, refresh, report]);
  const pick = (x: number, y: number, dimensions: StreamFrameDimensions) => {
    if (!canInspect || !frame) return;
    if (!snapshot || !report || performance.now() - report.at >= SNAPSHOT_LIFETIME_MS || !matchesFrame(snapshot, dimensions)) {
      pendingPick.current = { x, y, dimensions };
      setFeedback('Получаем актуальное дерево для выбранной точки…');
      void refresh();
      return;
    }
    const node = hitTestHierarchy(snapshot, x * snapshot.width / dimensions.width, y * snapshot.height / dimensions.height);
    select(node);
    setFeedback(node ? null : 'Android не предоставил узел в выбранной точке. Проверьте дерево: игровой Canvas может раскрывать только всю поверхность.');
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
        <Button variant={inspect ? 'default' : 'outline'} size="sm" disabled={!canInspect} aria-pressed={inspect} onClick={() => { if (inspect) { void refresh(); return; } invalidated(); setInspect(true); setAutomatic(true); setError(null); }}><ScanSearch className="mr-2 h-4 w-4" aria-hidden />XPath-инспектор</Button>
      </div>
      {inspect && <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" aria-pressed={automatic} disabled={!canInspect} onClick={() => { setAutomatic(!automatic); if (!automatic) { void refresh(); } }}>Автообновление: {automatic ? 'включено' : 'пауза'}</Button>
        <Button variant="outline" size="sm" disabled={!canInspect || !frame || pending} onClick={() => { void refresh(); }}><RefreshCw className={`mr-2 h-4 w-4 ${pending ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden />{pending ? 'Читаем дерево…' : 'Обновить дерево'}</Button>
      </div>}
    </div>
    {!canInspect && <PermissionNotice permission="device:write" action="чтение дерева Android через root-команды" />}
    <div className={inspect ? `grid min-w-0 items-start gap-4 ${compact ? '' : 'xl:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]'}` : 'min-w-0'}>
      <div className="min-w-0 overflow-hidden rounded-xl border border-border bg-black">
        <DeviceStream deviceId={deviceId} enableDiagnostics enableScreenshot enableNavigation enableStaticInput
          onControlSent={onControlSent}
          onControlCommand={onControlCommand}
          readOnly={controlDisabled || !access.can('stream:control')}
          readOnlyReason={controlDisabled ? 'Управление временно заблокировано на время проверки задания или при неподтверждённом результате.' : undefined}
          onFrameDimensions={onFrame} onInspectionInvalidated={invalidateFrame}
          inspection={inspect ? { onPick: pick, bounds: highlight } : undefined} />
      </div>
      {inspect && <aside className={`min-w-0 space-y-4 rounded-xl border border-border bg-card p-4 ${compact ? 'max-h-[480px] overflow-auto' : ''}`} aria-label="Элемент Android">
        <div><h4 className="font-semibold">Инспектор элементов</h4><p className="mt-1 text-xs leading-relaxed text-muted-foreground">Нажмите элемент на видео: границы и все возвращённые Android атрибуты появятся здесь. Выбор не отправляет нажатие Android.</p></div>
        <p className="text-xs leading-relaxed text-muted-foreground">UI Automator через root APK. Дерево и видео независимы. Автообновление — через 5 секунд после ответа, только в активном видимом инспекторе; при ошибке оно приостанавливается. Игровой Canvas может не раскрывать внутренних элементов.</p>
        {error && <p role="alert" className="break-words rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
        {pending && <p role="status" className="text-sm">Читаем полный снимок Android, до 50 секунд. Можно выбрать точку уже сейчас.</p>}
        {!snapshot ? !pending && <p role="status" className="text-sm text-muted-foreground">{frame ? 'Обновите дерево, чтобы повторить чтение.' : 'Ожидаем первый видеокадр. Дерево загрузится автоматически.'}</p>
            : <div className="space-y-2 text-xs text-muted-foreground"><p>{snapshot.width} × {snapshot.height} · поворот {snapshot.rotation * 90}° · {snapshot.nodes.length} элементов</p><p>Получено: {new Date(snapshot.completed_at).toLocaleTimeString('ru-RU')} · {Math.floor(age / 1000)} с назад</p>
              {!snapshot.temporary_file_cleanup_confirmed && <p role="status" className="text-amber-600 dark:text-amber-400">Удаление временного файла дерева не подтверждено. Проверьте связь и логи APK.</p>}
              {!valid && <p role="status" className="text-amber-600 dark:text-amber-400">{matchesFrame(snapshot, frame) ? 'Снимок устарел. Обновите дерево.' : 'Геометрия дерева не совпадает с видео. Обновите дерево после поворота.'}</p>}
              {snapshot.nodes.length === 0 && <p>Android не предоставил элементов для текущего окна.</p>}
            </div>}
        {feedback && <p role="status" className="rounded-lg border border-border bg-muted/40 p-3 text-xs leading-relaxed">{feedback}</p>}
        {valid && snapshot.nodes.length > 0 && <div className="space-y-2 border-t border-border pt-3">
          <Button variant="outline" size="sm" className="w-full" aria-expanded={showTree} onClick={() => setShowTree(!showTree)}>Дерево элементов · {snapshot.nodes.length}</Button>
          {showTree && <div className="max-h-64 space-y-1 overflow-auto" aria-label="Дерево Android">
            {snapshot.nodes.slice(0, treeLimit).map(node => <button key={node.id} type="button" aria-pressed={selected?.id === node.id} onClick={() => { select(node); setFeedback(node.bounds ? null : 'Android не предоставил видимые границы этого узла. Атрибуты доступны без подсветки.'); }}
              className={`block w-full rounded-lg border px-3 py-2 text-left text-xs ${selected?.id === node.id ? 'border-primary bg-primary/10' : 'border-transparent hover:bg-muted'}`}>
              <span className="block truncate font-medium">#{node.id} · {node.attributes.text || node.attributes['content-desc'] || node.attributes.class || 'Элемент'}</span>
              <span className="mt-1 block truncate font-mono text-muted-foreground">{node.attributes['resource-id'] || node.xpath}</span>
            </button>)}
            {snapshot.nodes.length > treeLimit && <Button variant="outline" size="sm" onClick={() => setTreeLimit(treeLimit + 200)}>Показать ещё 200</Button>}
          </div>}
        </div>}
        {valid && selected ? <div className="min-w-0 space-y-3">
          <div className="flex items-center justify-between gap-2"><h5 className="text-sm font-semibold">Узел #{selected.id} · глубина {selected.depth}</h5><Button size="sm" variant="ghost" aria-label="Копировать атрибуты элемента" onClick={() => { void copy(JSON.stringify(selected, null, 2)); }}><Copy className="h-4 w-4" aria-hidden /></Button></div>
          <div className="rounded-lg bg-muted p-3"><p className="text-xs font-medium">XPath</p><code className="mt-1 block break-all text-xs">{selected.xpath}</code><Button size="sm" variant="outline" className="mt-2" onClick={() => { void copy(selected.xpath); }}>Копировать XPath</Button></div>
          {onInsertSelector && snapshot && <Button size="sm" className="w-full" disabled={pending} onClick={() => { if (report && performance.now() - report.at < SNAPSHOT_LIFETIME_MS && matchesFrame(snapshot, frame)) onInsertSelector(selected, snapshot); }}>Добавить элемент в сценарий</Button>}
          <dl className="max-h-[min(60vh,640px)] space-y-2 overflow-auto text-xs">{Object.entries(selected.attributes).map(([key, value]) => <div key={key} className="border-b border-border pb-2"><dt className="font-medium text-muted-foreground">{key}</dt><dd className="mt-1 whitespace-pre-wrap break-all font-mono">{value || 'Пустое значение'}</dd></div>)}</dl>
        </div> : valid && snapshot.nodes.length > 0 && <p className="text-sm text-muted-foreground">Выберите элемент на изображении. Если границы не найдены, Android не раскрыл элемент в этой точке.</p>}
      </aside>}
    </div>
    {canInspect && <details className="rounded-xl border border-border bg-card p-3">
      <summary className="cursor-pointer text-sm font-semibold">Исходный PNG для пиксельных эталонов</summary>
      <div className="mt-3"><NativeScreenshotPanel key={deviceId} deviceId={deviceId} enabled={captureEnabled} /></div>
    </details>}
  </section>;
}
