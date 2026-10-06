'use client';
import { useState, useEffect, useRef, useCallback, Suspense, type DragEvent } from 'react';
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState, addEdge, type Node, type Edge, type Connection, type ReactFlowInstance, type FitViewOptions } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { ArrowLeft, Save, Check, Code2, Workflow, Undo2, Redo2, Download, Upload, Plus, Play, Search, Monitor, Settings2, PanelLeftClose, PanelLeftOpen, ScanSearch, MousePointer2, GitBranch, Smartphone, Maximize2, LayoutGrid, Trash2 } from 'lucide-react';
import { nodeTypes } from '@/lib/dag/nodeTypes';
import { exportDag, importDag, validateDag, ACTION_TYPES, type DagMetadata } from '@/lib/dag/export';
import { ACTION_LABELS, addDetachedAction, arrangeNodes, boundedSource, byteLength, draftKey, formatDag, initialDag, insertAction, parseSource, parseDraftSource, pushHistory, readDraft, SOURCE_LIMIT, writeDraft, type StudioDocument } from '@/lib/dag/studio';
import { ACTION_DRAG_TYPE, draggedAction, freeCanvasPosition, mergeCanvasPositions } from '@/lib/dag/canvasPlacement';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { RunScriptModal } from '@/components/sphere/RunScriptModal';
import { NodeInspector } from '@/src/features/scripts/studio/NodeInspector';
import { ConnectionInspector } from '@/src/features/scripts/studio/ConnectionInspector';
import { checkConnection, changeConnection } from '@/lib/dag/connections';
import { DeviceWorkbench } from '@/src/features/scripts/studio/DeviceWorkbench';
import { ACTION_GROUPS, ANDROID_KEY_PRESETS } from '@/src/features/scripts/studio/presentation';
import { layoutWorkflow } from '@/src/features/scripts/studio/layout';
import { useCanvasOverview } from '@/src/features/scripts/studio/useCanvasOverview';
import type { DagNode } from '@/lib/dag/export';
import { actionParameterErrors, ACTION_CONTRACT_VERSION } from '@/lib/dag/actionParameters';

interface ValidationReceipt { schema_version: 1; dag_hash: string; node_count: number; scope: 'structure-routes-lua-safety'; device_execution_verified: false;
  action_contract_version?: string; action_parameters_verified?: boolean }
const importedInitial = importDag(initialDag);
const overviewOptions: FitViewOptions = { padding: { top: '64px', right: '32px', bottom: '48px', left: '32px' }, minZoom: 0.15, maxZoom: 1 };
function errorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    if (error.response?.status === 409) return 'Версия сценария изменилась или он архивирован. Сохранение отклонено. Ваш исходник сохранён в редакторе; экспортируйте его и откройте актуальную версию из каталога.';
    const detail = error.response?.data?.detail;
    if (Array.isArray(detail)) return detail.slice(0, 20).map(row => `${Array.isArray(row.loc) ? row.loc.join('.') : 'DAG'}: ${String(row.msg ?? 'Ошибка')}`).join('\n');
    if (typeof detail === 'string') return detail.slice(0, 4096);
  }
  return error instanceof Error ? error.message : 'Операция не завершена. Проверьте связь; изменения остаются в редакторе.';
}

function BuilderInner({ editId, storageKey }: { editId: string | null; storageKey: string | null }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const access = useCapabilities();
  const accessRef = useRef(access); accessRef.current = access;
  const [direction, setDirection] = useState<'RIGHT' | 'DOWN'>('DOWN');
  const [nodes, setNodes, onNodesChange] = useNodesState(arrangeNodes(importedInitial.nodes, importedInitial.edges, initialDag.entry_node, 'DOWN'));
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(importedInitial.edges);
  const [metadata, setMetadata] = useState<DagMetadata>(importedInitial.metadata);
  const [document, setDocument] = useState<StudioDocument>({ name: 'Новый сценарий', source: formatDag(initialDag) });
  const documentRef = useRef(document); documentRef.current = document;
  const [mode, setMode] = useState<'graph' | 'source'>('graph');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [nodeSource, setNodeSource] = useState('');
  const [nodePending, setNodePending] = useState(false);
  const [canvasError, setCanvasError] = useState('');
  const [errors, setErrors] = useState('');
  const [receipt, setReceipt] = useState<{ fingerprint: string; result: ValidationReceipt } | null>(null);
  const [busy, setBusy] = useState<'check' | 'save' | null>(null);
  const [saveUncertain, setSaveUncertain] = useState(false);
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>(editId ? 'loading' : 'ready');
  const [loadError, setLoadError] = useState('');
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [expectedVersion, setExpectedVersion] = useState<{ id: string; version: number; dag_hash: string | null } | null>(null);
  const [baseDocument, setBaseDocument] = useState<StudioDocument | null>(editId ? null : document);
  const [history, setHistory] = useState<StudioDocument[]>([]);
  const [future, setFuture] = useState<StudioDocument[]>([]);
  const [search, setSearch] = useState('');
  const [addition, setAddition] = useState<'detached' | 'insert'>('detached');
  const [dropActive, setDropActive] = useState(false);
  const [draft, setDraft] = useState<StudioDocument | null>(null);
  const [localSave, setLocalSave] = useState(false);
  const [storageStatus, setStorageStatus] = useState('');
  const [runOpen, setRunOpen] = useState(false);
  const [workspace, setWorkspace] = useState<'design' | 'device'>('design');
  const [palette, setPalette] = useState(true);
  const [inspectorTab, setInspectorTab] = useState<'step' | 'scenario'>('step');
  const [layoutBusy, setLayoutBusy] = useState(false);
  const [execution, setExecution] = useState<{ last: string | null; logs: { node_id: string; success: boolean }[] }>({ last: null, logs: [] });
  const executionChanged = useCallback((last: string | null, logs: { node_id: string; success: boolean }[]) => setExecution({ last, logs }), []);
  const layoutRequest = useRef<AbortController | null>(null);
  const workbenchGuard = useRef<((silent?: boolean) => boolean) | null>(null);
  const registerWorkbenchGuard = useCallback((guard: ((silent?: boolean) => boolean) | null) => { workbenchGuard.current = guard; }, []);
  const request = useRef<AbortController | null>(null);
  const loaded = useRef(false);
  const canvas = useRef<ReactFlowInstance | null>(null);
  const canvasPane = useRef<HTMLDivElement>(null);
  const canvasLayout = useRef({ workspace, palette });
  const live = useRef(true);
  const inFlight = useRef(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const resource = editId ?? 'new';
  const fingerprint = JSON.stringify(document);
  const dirty = baseDocument?.name !== document.name || baseDocument?.source !== document.source || nodePending || Boolean(canvasError);
  const canRead = access.can('script:read');
  const canWrite = access.can('script:write');
  const writable = canWrite && !busy && loadState === 'ready';
  const selectedNode = nodes.find(node => node.id === selectedId);
  const selectedEdge = edges.find(edge => edge.id === selectedEdgeId);
  const { overview: fitOverview, manual: retainViewport, follow: followOverview } = useCanvasOverview(
    canvasPane, mode === 'graph' && canRead && loadState === 'ready', () => canvas.current?.fitView(overviewOptions),
  );

  useEffect(() => { live.current = true; return () => { live.current = false; request.current?.abort(); layoutRequest.current?.abort(); }; }, []);
  useEffect(() => {
    if (!canRead && busy) request.current?.abort();
  }, [canRead, busy]);
  useEffect(() => {
    const before = (event: BeforeUnloadEvent) => { if (dirty || workbenchGuard.current?.(true) === false) event.preventDefault(); };
    window.addEventListener('beforeunload', before);
    return () => window.removeEventListener('beforeunload', before);
  }, [dirty]);
  useEffect(() => {
    const changed = canvasLayout.current.workspace !== workspace || canvasLayout.current.palette !== palette;
    canvasLayout.current = { workspace, palette };
    if (!changed || mode !== 'graph' || !canRead || loadState !== 'ready') return;
    // Reframe only for an explicit panel change. Two frames let React Flow's
    // ResizeObserver measure the new pane before fitting; edits and run events
    // must preserve the operator's pan/zoom and node placement.
    let frame = window.requestAnimationFrame(() => {
      frame = window.requestAnimationFrame(() => { if (live.current) fitOverview(); });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [workspace, palette, mode, canRead, loadState, fitOverview]);

  function syncGraph(next: StudioDocument, placement?: { id: string; x: number; y: number }) {
    const imported = importDag(parseDraftSource(next.source), { editing: true });
    const arranged = arrangeNodes(imported.nodes, imported.edges, imported.metadata.entry_node, direction);
    setNodes(previous => mergeCanvasPositions(arranged, previous, placement));
    setEdges(imported.edges); setMetadata(imported.metadata); setSelectedEdgeId(null); setCanvasError('');
  }
  function remember() { const before = documentRef.current; setHistory(old => pushHistory(old, before)); setFuture([]); }
  function changeDocument(next: StudioDocument, graph = false, placement?: { id: string; x: number; y: number }) {
    boundedSource(next.source);
    if (graph) syncGraph(next, placement);
    remember(); setDocument(next); setReceipt(null); setErrors('');
  }
  function selectNode(node: Node) {
    if (nodePending) { setErrors('Примените или отмените параметры текущего шага перед выбором другого.'); return; }
    setSelectedId(node.id);
    setSelectedEdgeId(null);
    setInspectorTab('step');
    try { setNodeSource(JSON.stringify(exportDag(nodes, edges, metadata).nodes.find(item => item.id === node.id), null, 2)); }
    catch (error) { setErrors(errorMessage(error)); }
  }
  function restoreHistory(direction: 'undo' | 'redo') {
    if (!writable || nodePending) return;
    const stack = direction === 'undo' ? history : future;
    const next = stack.at(-1); if (!next) return;
    if (direction === 'undo') { setHistory(stack.slice(0, -1)); setFuture(old => pushHistory(old, document)); }
    else { setFuture(stack.slice(0, -1)); setHistory(old => pushHistory(old, document)); }
    let restoreError = '';
    if (mode === 'graph') {
      try { syncGraph(next); }
      catch (error) { setMode('source'); restoreError = errorMessage(error); }
    }
    setDocument(next); setSelectedId(null); setSelectedEdgeId(null); setNodePending(false); setReceipt(null); setErrors(restoreError); setCanvasError('');
  }
  // Loading owns the resource and never substitutes an empty template after a failed read.
  useEffect(() => {
    if (!editId || !canRead || loaded.current) return;
    let cancelled = false;
    const controller = new AbortController();
    setLoadState('loading'); setLoadError('');
    (async () => {
      try {
        const { data } = await api.get(`/scripts/${editId}?include_dag=true`, { signal: controller.signal });
        if (cancelled) return;
        if (data.id !== editId) throw new Error('Ответ относится к другому сценарию. Запись заблокирована.');
        const graph = data.current_version?.dag ?? data.dag;
        const imported = importDag(graph);
        boundedSource(formatDag(graph));
        const versionId = data.current_version_id ?? data.current_version?.id;
        if (typeof versionId !== 'string' || !versionId) throw new Error('Не получена версия сценария. Запись заблокирована.');
        if (data.is_archived) throw new Error('Архивный сценарий доступен только для чтения в каталоге.');
        const loadedDocument = { name: data.name ?? 'Без названия', source: formatDag(exportDag(imported.nodes, imported.edges, imported.metadata)) };
        setNodes(arrangeNodes(imported.nodes, imported.edges, imported.metadata.entry_node, direction)); setEdges(imported.edges); setMetadata(imported.metadata);
        setDocument(loadedDocument); setBaseDocument(loadedDocument);
        setExpectedVersion({ id: versionId, version: data.current_version?.version ?? 0, dag_hash: data.current_version?.dag_hash ?? null });
        loaded.current = true; setHistory([]); setFuture([]); setLoadState('ready');
      } catch (error) { if (!cancelled) { setLoadError(errorMessage(error)); setLoadState('error'); } }
    })();
    return () => { cancelled = true; controller.abort(); };
  }, [editId, loadAttempt, canRead, setNodes, setEdges]);

  useEffect(() => {
    if (!storageKey || !canRead) { setDraft(null); return; }
    try { setDraft(readDraft(localStorage.getItem(storageKey), resource)); }
    catch (error) { setStorageStatus(errorMessage(error)); }
  }, [storageKey, resource, canRead]);
  useEffect(() => {
    if (!localSave || !storageKey || !canWrite || loadState !== 'ready') return;
    const timer = window.setTimeout(() => {
      try { localStorage.setItem(storageKey, writeDraft(document, resource)); setStorageStatus('Черновик сохранён на этом ПК.'); }
      catch (error) { setStorageStatus(`Черновик не сохранён: ${errorMessage(error)}`); }
    }, 700);
    return () => window.clearTimeout(timer);
  }, [localSave, storageKey, canWrite, loadState, document, resource]);

  function publishCanvas(nextNodes: Node[], nextEdges: Edge[]) {
    try { changeDocument({ ...document, source: formatDag(exportDag(nextNodes, nextEdges, metadata)) }); setCanvasError(''); }
    catch (error) { setCanvasError(errorMessage(error)); setReceipt(null); }
  }
  const onConnect = (connection: Connection) => {
    if (!writable || nodePending) return;
    try { checkConnection(nodes, edges, connection); const nextEdges = addEdge(connection, edges); setEdges(nextEdges); publishCanvas(nodes, nextEdges); }
    catch (error) { setErrors(errorMessage(error)); }
  };
  const onReconnect = (edge: Edge, connection: Connection) => {
    if (!writable || nodePending) return;
    try { const nextEdges = changeConnection(nodes, edges, edge.id, connection); setEdges(nextEdges); publishCanvas(nodes, nextEdges); }
    catch (error) { setErrors(errorMessage(error)); }
  };
  function selectEdge(edge: Edge) {
    if (nodePending) { setErrors('Примените или отмените параметры текущего шага перед выбором связи.'); return; }
    setSelectedId(null); setSelectedEdgeId(edge.id); setInspectorTab('step');
  }
  function removeEdge() {
    if (!writable || nodePending || !selectedEdge) return;
    const nextEdges = edges.filter(edge => edge.id !== selectedEdge.id);
    setEdges(nextEdges); setSelectedEdgeId(null); publishCanvas(nodes, nextEdges);
  }
  function removeNode() {
    if (!writable || nodePending || !selectedId || selectedId === metadata.entry_node) return;
    const nextNodes = nodes.filter(node => node.id !== selectedId);
    const nextEdges = edges.filter(edge => edge.source !== selectedId && edge.target !== selectedId);
    setNodes(nextNodes); setEdges(nextEdges); setSelectedId(null); setSelectedEdgeId(null); publishCanvas(nextNodes, nextEdges);
  }
  // Selection and dragging are canvas-only; structural changes also invalidate validation.
  useEffect(() => {
    if (mode !== 'graph' || loadState !== 'ready') return;
    try {
      const source = formatDag(exportDag(nodes, edges, metadata));
      if (source !== documentRef.current.source) {
        const before = documentRef.current;
        setHistory(old => pushHistory(old, before)); setFuture([]);
        setDocument(old => ({ ...old, source })); setReceipt(null);
      }
      setCanvasError('');
    } catch (error) { setCanvasError(errorMessage(error)); setReceipt(null); }
  }, [nodes, edges, metadata, mode, loadState]);
  useEffect(() => {
    if (!selectedId || nodePending || mode !== 'graph') return;
    try { setNodeSource(JSON.stringify(exportDag(nodes, edges, metadata).nodes.find(node => node.id === selectedId), null, 2) ?? ''); }
    catch { /* The canvas error is shown and publishing stays blocked. */ }
  }, [selectedId, nodePending, nodes, edges, metadata, mode]);

  function addAction(type: typeof ACTION_TYPES[number], drop?: { x: number; y: number }, action?: DagNode['action']) {
    try {
      if (!writable || mode !== 'graph') return;
      if (nodePending) throw new Error('Сначала примените параметры выбранного шага.');
      const id = `step_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`;
      const detached = Boolean(drop) || addition === 'detached';
      const before = parseDraftSource(documentRef.current.source);
      const graph = detached ? addDetachedAction(before, type, id) : insertAction(before, type, id, selectedId ?? undefined);
      if (action) graph.nodes.find(node => node.id === id)!.action = structuredClone(action);
      let placement: { id: string; x: number; y: number } | undefined;
      if (detached) {
        const bounds = canvasPane.current?.getBoundingClientRect();
        if (!canvas.current || !bounds) throw new Error('Схема ещё не готова. Повторите добавление.');
        const position = drop ?? canvas.current.screenToFlowPosition({ x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 });
        if (!Number.isFinite(position.x) || !Number.isFinite(position.y)) throw new Error('Не получена позиция на схеме.');
        const origin = { x: position.x - 128, y: position.y - (drop ? 24 : 66) };
        placement = { id, ...(drop ? origin : freeCanvasPosition(nodes, origin)) };
      }
      changeDocument({ ...documentRef.current, source: formatDag(graph) }, true, placement);
      setSelectedId(id); setInspectorTab('step'); setNodeSource(JSON.stringify(graph.nodes.find(node => node.id === id), null, 2));
      retainViewport(); // A new/drop-focused step is no longer the whole-graph overview.
      // Dropping must preserve the current viewport and every existing position.
      if (!drop) window.requestAnimationFrame(() => { if (live.current) void canvas.current?.fitView({ nodes: [{ id }], padding: 0.15, minZoom: 0.85, maxZoom: 1 }); });
    } catch (error) { setErrors(errorMessage(error)); }
  }
  function startActionDrag(event: DragEvent, type: typeof ACTION_TYPES[number]) {
    if (!writable || nodePending || mode !== 'graph') { event.preventDefault(); return; }
    event.dataTransfer.setData(ACTION_DRAG_TYPE, type); event.dataTransfer.effectAllowed = 'copy';
  }
  function dropAction(event: DragEvent) {
    setDropActive(false);
    if (!event.dataTransfer.types.includes(ACTION_DRAG_TYPE)) return;
    event.preventDefault();
    if (!writable || nodePending || mode !== 'graph' || !canvas.current) return;
    const type = draggedAction(event.dataTransfer.getData(ACTION_DRAG_TYPE));
    if (!type) { setErrors('Неизвестное действие. Граф не изменён.'); return; }
    addAction(type, canvas.current.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
  }
  function applyNode() {
    try {
      const graph = parseDraftSource(document.source);
      const value = JSON.parse(boundedSource(nodeSource));
      if (value.id !== selectedId) throw new Error('ID выбранного шага менять здесь нельзя. Переименование со всеми ссылками доступно в исходнике.');
      graph.nodes = graph.nodes.map(node => node.id === selectedId ? value : node);
      changeDocument({ ...document, source: formatDag(graph) }, true); setNodePending(false);
    } catch (error) { setErrors(errorMessage(error)); }
  }
  function getDraftDag() {
    if (nodePending) throw new Error('Параметры шага ещё не применены.');
    if (canvasError) throw new Error(canvasError);
    const dag = parseSource(documentRef.current.source);
    const parameterErrors = actionParameterErrors(dag.nodes);
    if (parameterErrors.length) throw new Error(parameterErrors.slice(0, 20).map(error => `${error.loc.join('.')}: ${error.msg}`).join('\n'));
    if (!documentRef.current.name.trim() || documentRef.current.name.length > 255) throw new Error('Название сценария: 1–255 символов.');
    return dag;
  }
  async function checkOrSave(operation: 'check' | 'save') {
    if (inFlight.current || loadState !== 'ready' || !accessRef.current.can(operation === 'save' ? 'script:write' : 'script:read')) return;
    if (operation === 'save' && saveUncertain) return;
    if (operation === 'save' && workbenchGuard.current && !workbenchGuard.current()) return;
    const submitted = documentRef.current;
    const sentFingerprint = JSON.stringify(submitted);
    const controller = new AbortController(); request.current = controller;
    let saveSubmitted = false;
    try {
      const dag = getDraftDag();
      inFlight.current = true; setBusy(operation); setErrors('');
      if (operation === 'check') {
        const { data } = await api.post<ValidationReceipt>('/scripts/validate', { dag }, { signal: controller.signal });
        if (!live.current || controller.signal.aborted || JSON.stringify(documentRef.current) !== sentFingerprint || !accessRef.current.can('script:read')) return;
        if (data.schema_version !== 1 || data.scope !== 'structure-routes-lua-safety' || data.device_execution_verified !== false
          || !/^[a-f0-9]{64}$/.test(data.dag_hash) || data.node_count !== dag.nodes.length) throw new Error('Ответ проверки не соответствует контракту.');
        if ((data.action_contract_version !== undefined || data.action_parameters_verified !== undefined)
          && (data.action_contract_version !== ACTION_CONTRACT_VERSION || data.action_parameters_verified !== true)) throw new Error('Версия серверного контракта параметров не подтверждена. Проверка не принята.');
        setReceipt({ fingerprint: sentFingerprint, result: data });
      } else {
        if (editId) {
          if (!expectedVersion?.id) throw new Error('Версия неизвестна. Откройте актуальный сценарий из каталога.');
          saveSubmitted = true;
          await api.put(`/scripts/${editId}`, { name: submitted.name.trim(), dag, expected_current_version_id: expectedVersion.id }, { signal: controller.signal });
        } else {
          saveSubmitted = true;
          await api.post('/scripts', { name: submitted.name.trim(), dag }, { signal: controller.signal });
        }
        if (!live.current || controller.signal.aborted || !accessRef.current.can('script:write')) return;
        await queryClient.invalidateQueries({ queryKey: ['scripts'] });
        if (live.current) { setBaseDocument(submitted); router.push('/scripts'); }
      }
    } catch (error) { if (live.current && !controller.signal.aborted) {
      if (operation === 'save' && saveSubmitted && !(isAxiosError(error) && error.response && error.response.status >= 400 && error.response.status < 500)) {
        setSaveUncertain(true);
        setErrors('Результат сохранения неизвестен: сервер мог принять запрос. Повтор заблокирован в этом редакторе. Экспортируйте исходник и проверьте каталог и историю версий перед новым сохранением.');
      } else setErrors(errorMessage(error));
    } }
    finally { inFlight.current = false; if (live.current) setBusy(null); }
  }
  async function importFile(file: File | undefined) {
    if (!file) return;
    try {
      if (file.size > SOURCE_LIMIT) throw new Error('Файл превышает 512 KiB.');
      const source = boundedSource(await file.text());
      if (!live.current || !accessRef.current.can('script:write')) return;
      // Invalid source is retained for repair; it cannot publish the old graph.
      changeDocument({ ...documentRef.current, source }); setMode('source'); setSelectedId(null); setSelectedEdgeId(null); setNodePending(false);
    } catch (error) { if (live.current) setErrors(errorMessage(error)); }
  }
  function exportFile() {
    const url = URL.createObjectURL(new Blob([document.source], { type: 'application/json;charset=utf-8' }));
    const link = window.document.createElement('a'); link.href = url; link.download = 'sphere-scenario.json'; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function switchMode(nextMode: 'source' | 'graph') {
    try {
      if (nodePending) throw new Error('Примените или отмените параметры шага.');
      if (nextMode === 'graph') syncGraph(document);
      setMode(nextMode); setErrors(''); setSelectedId(null); setSelectedEdgeId(null);
    } catch (error) { setErrors(errorMessage(error)); }
  }
  function leave() {
    if (workbenchGuard.current && !workbenchGuard.current()) return;
    if (!dirty || window.confirm('Есть несохранённые изменения. Выйти из редактора?')) router.push('/scripts');
  }
  async function arrange() {
    if (layoutBusy) return;
    const controller = new AbortController(); layoutRequest.current = controller;
    const original = documentRef.current.source;
    setLayoutBusy(true);
    try { const next = await layoutWorkflow(nodes, edges, controller.signal, direction);
      if (live.current && documentRef.current.source === original) { setNodes(next); window.requestAnimationFrame(() => { if (live.current) fitOverview(); }); }
    } catch (reason) { if (live.current && !controller.signal.aborted) setErrors(errorMessage(reason)); }
    finally { if (live.current) setLayoutBusy(false); layoutRequest.current = null; }
  }
  function insertRecorded(actions: DagNode['action'][]): boolean {
    try {
      if (!writable || nodePending) throw new Error('Сначала примените параметры шага.');
      let graph = parseDraftSource(documentRef.current.source);
      if (graph.nodes.length + actions.length > 500) throw new Error('Запись превышает лимит 500 шагов. Граф не изменён.');
      let selected = selectedId ?? undefined;
      for (const action of actions) {
        const id = `step_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`;
        graph = insertAction(graph, action.type as typeof ACTION_TYPES[number], id, selected);
        graph.nodes.find(node => node.id === id)!.action = structuredClone(action);
        selected = id;
      }
      changeDocument({ ...documentRef.current, source: formatDag(graph) }, true); setSelectedId(selected ?? null);
      setNodeSource(JSON.stringify(graph.nodes.find(node => node.id === selected), null, 2)); setMode('graph');
      return true;
    } catch (reason) { setErrors(errorMessage(reason)); return false; }
  }
  if (!canRead) return <div role="status" className="p-6">{access.pending ? 'Проверяем права доступа к сценариям…' : 'Не подтверждено право чтения сценариев.'}</div>;
  if (loadState === 'loading') return <div role="status" className="p-6">Загружаем исходник и версию сценария…</div>;
  if (loadState === 'error') return <div className="mx-auto max-w-xl p-6"><div role="alert" className="space-y-4 rounded-xl border bg-card p-6">
    <h1 className="text-lg font-semibold">Сценарий не загружен</h1><p>{loadError}</p>
    <p>Редактирование и сохранение недоступны до успешной загрузки исходного графа.</p>
    <Button onClick={() => setLoadAttempt(old => old + 1)}>Повторить загрузку</Button> <Button variant="outline" onClick={leave}>К каталогу сценариев</Button>
  </div></div>;
  const currentReceipt = receipt?.fingerprint === fingerprint ? receipt.result : null;
  const available = ACTION_TYPES.filter(type => `${type} ${ACTION_LABELS[type]}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const canRun = !dirty && editId && expectedVersion?.dag_hash && access.can('script:execute');
  let draftIssues: string[] = [];
  if (mode === 'graph' && !canvasError) {
    try { draftIssues = validateDag(exportDag(nodes, edges, metadata)); } catch { /* Canvas error owns malformed state. */ }
  }
  const paintedNodes: Node[] = nodes.map(node => ({ ...node, selected: node.id === selectedId || node.selected, data: { ...node.data, layoutDirection: direction,
    execution: execution.logs.findLast(log => log.node_id === node.id)?.success === true ? 'success'
      : execution.logs.findLast(log => log.node_id === node.id)?.success === false ? 'failed'
      : execution.last === node.id ? 'reported' : null } }));
  const paintedEdges: Edge[] = edges.map(edge => ({ ...edge, selected: edge.id === selectedEdgeId || edge.selected, type: 'smoothstep', interactionWidth: 28,
    pathOptions: { borderRadius: 18, offset: 30 },
    markerEnd: { type: 'arrowclosed' as const, width: 16, height: 16, color: edge.sourceHandle === 'failure' ? '#f43f5e' : edge.sourceHandle === 'false_branch' ? '#d97706' : edge.sourceHandle === 'true_branch' ? '#10b981' : 'hsl(var(--primary))' },
    style: { strokeWidth: edge.id === selectedEdgeId ? 3 : 1.7, stroke: edge.sourceHandle === 'failure' ? '#f43f5e' : edge.sourceHandle === 'false_branch' ? '#d97706' : edge.sourceHandle === 'true_branch' ? '#10b981' : 'hsl(var(--primary))' },
    label: edge.sourceHandle === 'failure' ? 'Ошибка' : edge.sourceHandle === 'true_branch' ? 'Да' : edge.sourceHandle === 'false_branch' ? 'Нет' : undefined,
    labelStyle: { fontSize: 10, fill: 'hsl(var(--foreground))' }, labelBgStyle: { fill: 'hsl(var(--card))', fillOpacity: 1 }, labelBgPadding: [6, 4] as [number, number], labelBgBorderRadius: 5,
  }));
  return <section aria-label="Script Studio" className="studio-workspace flex min-h-[600px] min-w-0 flex-col bg-background lg:h-[calc(100dvh-4rem)] lg:min-h-0">
    <header className="shrink-0 border-b bg-card">
      <div className="flex flex-col gap-3 px-4 py-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex w-full min-w-0 items-center gap-3 xl:flex-1"><Button variant="ghost" size="icon" className="shrink-0" aria-label="К каталогу сценариев" onClick={leave}><ArrowLeft className="size-4" /></Button>
          <div className="min-w-0 flex-1"><div className="mb-1 flex flex-wrap items-center gap-2 text-[10px] font-medium uppercase tracking-[.14em] text-muted-foreground"><Workflow className="size-3 shrink-0 text-primary" />Script Studio <span className="rounded border px-1.5 py-0.5 tracking-normal">DAG 1.0</span></div>
            <label className="sr-only" htmlFor="studio-name">Название сценария</label><Input id="studio-name" value={document.name} maxLength={255} readOnly={!writable} className="h-8 max-w-xl border-transparent bg-transparent px-0 text-lg font-semibold shadow-none hover:border-border focus:px-2" onChange={event => changeDocument({ ...document, name: event.target.value })} /></div>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2 xl:justify-end"><span className={`rounded-full border px-2.5 py-1 text-[11px] ${dirty ? 'border-amber-500/30 bg-amber-500/5 text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}>{dirty ? 'Есть изменения' : expectedVersion ? `Версия ${expectedVersion.version}` : 'Новый сценарий'}</span>
          <Button size="sm" variant="outline" disabled={Boolean(busy) || nodePending || Boolean(canvasError)} onClick={() => void checkOrSave('check')}><Check className="mr-2 size-3.5" />{busy === 'check' ? 'Проверяем…' : 'Проверить на сервере'}</Button>
          <Button size="sm" disabled={!writable || nodePending || Boolean(canvasError) || saveUncertain} onClick={() => void checkOrSave('save')}><Save className="mr-2 size-3.5" />{busy === 'save' ? 'Сохраняем…' : editId ? 'Сохранить версию' : 'Создать сценарий'}</Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-2">
        <div className="flex flex-wrap items-center gap-1.5"><div className="flex gap-1 rounded-lg bg-muted p-1" role="group" aria-label="Представление сценария"><Button size="sm" variant={mode === 'graph' ? 'secondary' : 'ghost'} aria-pressed={mode === 'graph'} onClick={() => switchMode('graph')}><Workflow className="mr-1.5 size-3.5" />Граф</Button><Button size="sm" variant={mode === 'source' ? 'secondary' : 'ghost'} aria-pressed={mode === 'source'} onClick={() => switchMode('source')}><Code2 className="mr-1.5 size-3.5" />JSON</Button></div>
          <Button variant="ghost" size="icon" aria-label="Отменить изменение" disabled={!writable || nodePending || !history.length} onClick={() => restoreHistory('undo')}><Undo2 className="size-4" /></Button><Button variant="ghost" size="icon" aria-label="Повторить изменение" disabled={!writable || nodePending || !future.length} onClick={() => restoreHistory('redo')}><Redo2 className="size-4" /></Button>
          <span className="mx-1 h-5 border-l" /><Button size="sm" variant="ghost" disabled={!writable || nodePending} onClick={() => fileInput.current?.click()}><Upload className="mr-1.5 size-3.5" />Импорт JSON</Button><input ref={fileInput} type="file" accept=".json,application/json" className="hidden" aria-label="Файл сценария" onChange={event => { void importFile(event.target.files?.[0]); event.target.value = ''; }} /><Button size="sm" variant="ghost" onClick={exportFile}><Download className="mr-1.5 size-3.5" />Экспорт</Button>
          {mode === 'graph' && <Button size="sm" variant="ghost" disabled={Boolean(busy) || nodePending || layoutBusy} onClick={() => void arrange()} title="Раскладка ELK в локальном worker"><LayoutGrid className="mr-1.5 size-3.5" />{layoutBusy ? 'Раскладываем…' : 'Упорядочить'}</Button>}
          {mode === 'graph' && <select aria-label="Направление схемы" value={direction} disabled={layoutBusy || nodePending || Boolean(busy)} className="h-8 rounded-lg border bg-card px-2 text-xs" onChange={event => { const next = event.target.value === 'RIGHT' ? 'RIGHT' : 'DOWN'; setDirection(next); setNodes(arrangeNodes(nodes, edges, metadata.entry_node, next)); window.requestAnimationFrame(() => { if (live.current) fitOverview(); }); }}><option value="DOWN">Сверху вниз</option><option value="RIGHT">Слева направо</option></select>}
        </div>
        <div className="flex flex-wrap gap-2"><Button size="sm" variant={workspace === 'device' ? 'secondary' : 'outline'} aria-pressed={workspace === 'device'} onClick={() => { if (workspace === 'device' && workbenchGuard.current && !workbenchGuard.current()) return; setWorkspace(workspace === 'device' ? 'design' : 'device'); }}><Monitor className="mr-2 size-3.5" />{workspace === 'device' ? 'Закрыть устройство' : 'Устройство · запись · проверка'}</Button><Button size="sm" variant="outline" disabled={!canRun || Boolean(busy)} onClick={() => setRunOpen(true)} title="Запуск сохранённой неизменённой версии на выбранных целях"><Play className="mr-2 size-3.5" />Запустить версию</Button></div>
      </div>
      {!canWrite && <p role="status" className="px-4 pb-2 text-xs text-muted-foreground">Исходник доступен для чтения и проверки. Права записи не подтверждены.</p>}
    </header>
    {(errors || canvasError) && <div role="alert" className="max-h-28 shrink-0 overflow-auto whitespace-pre-wrap border-b border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">{errors || canvasError}</div>}
    {draftIssues.length > 0 && <details aria-label="Граф не готов к публикации" className="shrink-0 border-b bg-amber-500/10 px-4 py-2 text-xs"><summary className="cursor-pointer font-medium">Черновик графа · {draftIssues.length} замечаний перед публикацией</summary><p className="mt-2 text-muted-foreground">Отдельные шаги и незавершённые ветки можно редактировать. Соедините их до проверки и сохранения версии.</p><ul className="mt-2 max-h-24 list-disc overflow-auto pl-4">{draftIssues.slice(0, 20).map((issue, index) => <li key={index}>{issue}</li>)}</ul>{draftIssues.length > 20 && <p className="mt-1">Показаны первые 20 замечаний.</p>}</details>}
    {currentReceipt && <div role="status" className="shrink-0 border-b bg-emerald-500/10 px-4 py-2 text-xs">Структура, переходы и безопасность Lua проверены · {currentReceipt.node_count} шагов <span className="font-mono" title={currentReceipt.dag_hash}>· SHA256 {currentReceipt.dag_hash.slice(0, 12)}</span>. {currentReceipt.action_parameters_verified ? `Параметры действий проверены сервером · контракт ${currentReceipt.action_contract_version}.` : 'Параметры проверены локально; этот API не подтвердил проверку параметров.'} Выполнение на Android не проверялось.</div>}
    {draft && <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-amber-500/10 px-4 py-2 text-xs"><span>Найден локальный черновик этого сценария.</span><Button size="sm" variant="outline" disabled={!writable} onClick={() => { try { changeDocument(draft); setMode('source'); setNodePending(false); setSelectedId(null); setDraft(null); } catch (error) { setErrors(errorMessage(error)); } }}>Восстановить черновик</Button><Button size="sm" variant="ghost" onClick={() => { try { if (storageKey) localStorage.removeItem(storageKey); setDraft(null); } catch (error) { setStorageStatus(errorMessage(error)); } }}>Удалить черновик</Button></div>}
    <div className={`flex min-h-0 min-w-0 flex-col lg:flex-1 ${workspace === 'device' ? 'studio-device-workspace lg:grid lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]' : 'lg:flex-row'}`}>
      {workspace === 'design' && palette && <aside aria-label="Каталог действий" className="flex max-h-[420px] shrink-0 flex-col border-b bg-card lg:max-h-none lg:w-[224px] lg:border-b-0 lg:border-r">
        <div className="space-y-3 border-b p-3"><div className="flex items-center justify-between"><h2 className="text-xs font-semibold">Библиотека действий <span className="ml-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{ACTION_TYPES.length}</span></h2><Button size="icon" variant="ghost" aria-label="Скрыть библиотеку действий" className="size-7" onClick={() => setPalette(false)}><PanelLeftClose className="size-3.5" /></Button></div><div className="relative"><Search className="absolute left-2 top-2.5 size-3.5 text-muted-foreground" /><Input placeholder="Найти действие…" className="h-8 pl-7 text-xs" aria-label="Поиск действия" value={search} onChange={event => setSearch(event.target.value)} /></div><label htmlFor="studio-addition" className="sr-only">Способ добавления действия</label><select id="studio-addition" aria-label="Способ добавления действия" className="h-8 w-full rounded-lg border bg-background px-2 text-xs" value={addition} disabled={!writable || nodePending || mode !== 'graph'} onChange={event => setAddition(event.target.value === 'insert' ? 'insert' : 'detached')}><option value="detached">Отдельный узел</option><option value="insert">Вставить в цепочку</option></select></div>
        <div className="min-h-0 flex-1 overflow-auto px-2 pb-4">{!search && <details aria-label="Готовые клавиши Android" className="mt-3 rounded-lg border bg-muted/20 p-2"><summary className="cursor-pointer text-[11px] font-medium">Клавиши Android · 6</summary><div className="mt-3 grid grid-cols-2 gap-1.5">{ANDROID_KEY_PRESETS.map(key => <Button key={key.keycode} size="sm" variant="outline" className="h-8 text-[11px]" aria-label={`Добавить действие ${key.label}`} disabled={!writable || mode !== 'graph' || nodePending} onClick={() => addAction('key_event', undefined, { type: 'key_event', keycode: key.keycode })}>{key.label}</Button>)}</div><p className="mt-2 text-[10px] leading-4 text-muted-foreground">Добавляют шаг выбранным способом. Android сейчас не управляется.</p></details>}{ACTION_GROUPS.map((group, index) => { const types = available.filter(type => (group.types as readonly string[]).includes(type)); const Icon = [MousePointer2, ScanSearch, GitBranch, Smartphone][index]; return types.length ? <div key={group.name} className="mt-4"><h3 className="mb-2 flex items-center gap-2 px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"><Icon className="size-3" />{group.name}</h3>{types.map(type => <button key={type} type="button" aria-label={`Добавить узел: ${ACTION_LABELS[type]}`} draggable={writable && mode === 'graph' && !nodePending} onDragStart={event => startActionDrag(event, type)} onDragEnd={() => setDropActive(false)} disabled={!writable || mode !== 'graph' || nodePending} title="Перетащите на схему или добавьте нажатием" className="group flex w-full cursor-grab items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors hover:bg-muted active:cursor-grabbing disabled:cursor-default disabled:opacity-40" onClick={() => addAction(type)}><span className="min-w-0 flex-1"><span className="block text-xs font-medium">{ACTION_LABELS[type]}</span><span className="block font-mono text-[9px] text-muted-foreground">{type}</span></span><Plus className="size-3 shrink-0 text-muted-foreground group-hover:text-primary" /></button>)}</div> : null; })}{!available.length && <p className="p-3 text-xs text-muted-foreground">Действия не найдены.</p>}</div>
        <p className="border-t px-3 py-2 text-[10px] leading-4 text-muted-foreground">{addition === 'detached' ? 'Свободная сборка: добавьте шаг, затем соедините его выходы.' : 'Вставка после выбранного линейного шага; прежний переход сохраняется.'} Перетаскивание всегда создаёт отдельный узел.</p>
      </aside>}
      <div ref={canvasPane} aria-label="Поле графа" onDrop={dropAction} onDragOver={event => { if (writable && !nodePending && mode === 'graph' && event.dataTransfer.types.includes(ACTION_DRAG_TYPE)) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; setDropActive(true); } }} onDragLeave={event => { if (!event.relatedTarget || !event.currentTarget.contains(event.relatedTarget as globalThis.Node)) setDropActive(false); }} className={`relative h-[440px] min-w-0 flex-none lg:h-auto lg:min-h-0 lg:flex-1 ${workspace === 'device' ? 'lg:basis-[45%]' : ''}`}>
        {dropActive && writable && !nodePending && mode === 'graph' && <div className="pointer-events-none absolute inset-1 z-20 flex items-end justify-center rounded-xl border-2 border-dashed border-primary bg-primary/5 p-5"><span className="rounded-lg border bg-card px-3 py-2 text-xs shadow-sm">Отпустите, чтобы добавить отдельный узел</span></div>}
        <div className="absolute left-3 top-3 z-10 flex gap-1 rounded-lg border bg-card/95 p-1 shadow-sm">{workspace === 'design' && !palette && <Button variant="ghost" size="icon" className="size-7" aria-label="Показать библиотеку действий" onClick={() => setPalette(true)}><PanelLeftOpen className="size-3.5" /></Button>}<Button size="sm" variant="ghost" className="h-7 text-[11px]" onClick={fitOverview}><Maximize2 className="mr-1.5 size-3" />Весь граф</Button><span className="flex items-center px-2 text-[10px] text-muted-foreground">{nodes.length} шагов · {edges.length} связей</span></div>
        {mode === 'source' ? <div className="flex h-full min-h-[440px] flex-col bg-muted/20 p-4 pt-14 lg:min-h-0"><label htmlFor="studio-source" className="mb-2 text-xs font-medium">Исходник DAG 1.0 · {byteLength(document.source).toLocaleString('ru-RU')} байт / 512 KiB</label><textarea id="studio-source" spellCheck={false} className="min-h-[280px] flex-1 resize-none rounded-xl border bg-card p-4 font-mono text-xs leading-6 outline-none focus:ring-2 focus:ring-ring" value={document.source} readOnly={!writable} onChange={event => { try { changeDocument({ ...document, source: event.target.value }); } catch (error) { setErrors(errorMessage(error)); } }} /><p className="mt-2 text-[11px] text-muted-foreground">JSON и граф — один сценарий. Некорректный текст сохраняется для исправления, публикация блокируется.</p></div>
          : <ReactFlow nodes={paintedNodes} edges={paintedEdges} onNodesChange={writable && !nodePending ? onNodesChange : undefined} onEdgesChange={writable && !nodePending ? onEdgesChange : undefined} onConnect={onConnect} onReconnect={onReconnect} edgesReconnectable={writable && !nodePending} reconnectRadius={16} onEdgeClick={(_, edge) => selectEdge(edge)} onNodeClick={(_, node) => selectNode(node)} onMoveStart={event => { if (event) retainViewport(); }} onNodeDragStart={retainViewport} nodeTypes={nodeTypes} fitView fitViewOptions={overviewOptions} minZoom={0.15} maxZoom={1.8} nodesDraggable={writable && !nodePending} nodesConnectable={writable && !nodePending} onBeforeDelete={async deletion => { if (!writable || nodePending) return false; if (deletion.nodes.some(node => node.id === metadata.entry_node)) { setErrors('Начальный шаг нельзя удалить. Сначала выберите другой вход в настройках сценария.'); return false; } return true; }} deleteKeyCode={writable && !nodePending ? ['Backspace', 'Delete'] : null} onInit={instance => { canvas.current = instance; }} className="sphere-studio-flow"><Background gap={24} color="hsl(var(--border))" /><Controls fitViewOptions={overviewOptions} onFitView={followOverview} onZoomIn={retainViewport} onZoomOut={retainViewport} /><MiniMap className="!hidden xl:!block" style={{ width: 130, height: 85 }} pannable zoomable nodeColor="hsl(var(--primary) / .5)" /></ReactFlow>}
        {workspace === 'device' && mode === 'graph' && selectedEdge && <div className="absolute bottom-3 left-3 z-10 max-h-[calc(100%_-_4rem)] w-[280px] max-w-[calc(100%_-_1.5rem)] overflow-auto rounded-xl border bg-card p-4 shadow-lg"><Button size="sm" variant="ghost" className="mb-2 w-full" onClick={() => setSelectedEdgeId(null)}>Закрыть редактор связи</Button><ConnectionInspector edge={selectedEdge} nodes={nodes} writable={writable && !nodePending} reconnect={connection => onReconnect(selectedEdge, connection)} remove={removeEdge} /></div>}
      </div>
      {workspace === 'device' ? <div className="min-h-0 min-w-0 border-t lg:flex-[1.2] lg:border-l lg:border-t-0"><DeviceWorkbench scriptId={editId} version={expectedVersion} name={document.name} canRun={Boolean(canRun)} canEdit={writable && !nodePending} onInsert={insertRecorded} onExecution={executionChanged} registerCloseGuard={registerWorkbenchGuard} /></div>
        : <aside aria-label="Параметры шага" className="flex min-h-0 shrink-0 flex-col border-t bg-card lg:w-[310px] lg:border-l lg:border-t-0 2xl:w-[350px]">
          <div className="flex gap-1 border-b p-2" role="group" aria-label="Настройки Studio"><Button size="sm" variant={inspectorTab === 'step' ? 'secondary' : 'ghost'} className="flex-1" onClick={() => setInspectorTab('step')}>Шаг</Button><Button size="sm" variant={inspectorTab === 'scenario' ? 'secondary' : 'ghost'} className="flex-1" onClick={() => setInspectorTab('scenario')}><Settings2 className="mr-2 size-3.5" />Сценарий</Button></div>
          <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
            {inspectorTab === 'step' ? selectedEdge && mode === 'graph' ? <ConnectionInspector edge={selectedEdge} nodes={nodes} writable={writable && !nodePending} reconnect={connection => onReconnect(selectedEdge, connection)} remove={removeEdge} /> : selectedNode && mode === 'graph' ? <><div><h2 className="text-sm font-semibold">{ACTION_LABELS[(selectedNode.data.action as { type: typeof ACTION_TYPES[number] }).type]}</h2><p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">{selectedId}</p></div><NodeInspector key={selectedId} source={nodeSource} nodes={nodes} writable={writable} pending={nodePending} onChange={value => { try { setNodeSource(boundedSource(value)); setNodePending(true); setReceipt(null); } catch (reason) { setErrors(errorMessage(reason)); } }} apply={applyNode} cancel={() => { setNodePending(false); setNodeSource(JSON.stringify(parseDraftSource(document.source).nodes.find(node => node.id === selectedId), null, 2)); setErrors(''); }} /><Button size="sm" variant="outline" className="w-full text-destructive" disabled={!writable || nodePending || selectedId === metadata.entry_node} title={selectedId === metadata.entry_node ? 'Сначала выберите другой начальный шаг в настройках сценария' : 'Удаляет шаг и его связи; отмена доступна в истории'} onClick={removeNode}><Trash2 className="mr-2 size-3.5" />Удалить шаг</Button></>
              : <div className="space-y-5"><div className="rounded-xl border border-dashed bg-muted/20 px-4 py-6 text-center"><MousePointer2 className="mx-auto mb-3 size-6 text-muted-foreground" /><h2 className="text-sm font-semibold">Выберите шаг или связь</h2><p className="mt-2 text-xs leading-5 text-muted-foreground">Нажмите на шаг для настройки действия или на линию для изменения и удаления перехода. Конец связи можно перетащить на другой шаг.</p></div><ol className="space-y-4 text-xs"><li className="flex gap-3"><span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 font-mono text-primary">1</span><div className="leading-5"><strong>Соберите сценарий</strong><p className="text-muted-foreground">Добавьте действия из библиотеки или импортируйте JSON.</p></div></li><li className="flex gap-3"><span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 font-mono text-primary">2</span><div className="leading-5"><strong>Выберите Android</strong><p className="text-muted-foreground">Откройте живое устройство, запишите действия или добавьте XPath.</p></div></li><li className="flex gap-3"><span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 font-mono text-primary">3</span><div className="leading-5"><strong>Проверьте и сохраните</strong><p className="text-muted-foreground">Структура проверяется сервером. Работу на Android подтвердит отдельное задание.</p></div></li></ol><Button size="sm" variant="outline" className="w-full" onClick={() => setWorkspace('device')}><Monitor className="mr-2 size-3.5" />Выбрать устройство</Button></div>
              : <div className="space-y-5"><div><h2 className="text-sm font-semibold">Настройки сценария</h2><p className="mt-1 text-xs text-muted-foreground">Общие параметры и восстановление работы</p></div>
                <label className="block space-y-2 text-xs font-medium">Начальный шаг<select aria-label="Начальный шаг сценария" className="h-9 w-full rounded-md border bg-background px-2 text-xs" value={metadata.entry_node} disabled={!writable || nodePending || mode !== 'graph'} onChange={event => { try { const dag = parseDraftSource(document.source); dag.entry_node = event.target.value; changeDocument({ ...document, source: formatDag(dag) }, true); } catch (reason) { setErrors(errorMessage(reason)); } }}>{nodes.map(node => <option key={node.id} value={node.id}>{node.id}</option>)}</select></label>
                <label className="block space-y-2 text-xs font-medium">Таймаут всего сценария, мс<Input type="number" min={1000} max={86400000} value={metadata.timeout_ms ?? 1800000} readOnly={!writable || nodePending || mode !== 'graph'} onChange={event => { try { const dag = parseDraftSource(document.source); dag.timeout_ms = Number(event.target.value); changeDocument({ ...document, source: formatDag(dag) }, true); } catch (reason) { setErrors(errorMessage(reason)); } }} /></label>
                <label className="block space-y-2 text-xs font-medium">Описание<textarea className="min-h-24 w-full rounded-md border bg-background p-2 text-xs leading-5" maxLength={2000} value={metadata.description ?? ''} readOnly={!writable || nodePending || mode !== 'graph'} onChange={event => { try { const dag = parseDraftSource(document.source); dag.description = event.target.value; changeDocument({ ...document, source: formatDag(dag) }, true); } catch (reason) { setErrors(errorMessage(reason)); } }} /></label>
                <dl className="space-y-3 rounded-xl border bg-muted/20 p-3 text-xs"><div><dt className="text-muted-foreground">Вход в сценарий</dt><dd className="mt-1 break-all font-mono">{metadata.entry_node}</dd></div><div><dt className="text-muted-foreground">Версия</dt><dd className="mt-1">{expectedVersion ? `v${expectedVersion.version}` : 'Ещё не опубликован'}</dd></div>{expectedVersion?.dag_hash && <div><dt className="text-muted-foreground">Базовый SHA-256</dt><dd className="mt-1 break-all font-mono text-[10px]">{expectedVersion.dag_hash}</dd></div>}</dl>
                <label className="flex items-start gap-2 text-xs leading-5"><input type="checkbox" checked={localSave} disabled={!writable || !storageKey} onChange={event => setLocalSave(event.target.checked)} /><span>Сохранять полный исходник на этом ПК<span className="block text-muted-foreground">До 512 KiB, восстановление 7 дней. Может содержать приватный текст и код; неприменённые параметры не сохраняются.</span></span></label>{storageStatus && <p role="status" className="text-xs text-muted-foreground">{storageStatus}</p>}{storageKey && <Button size="sm" variant="outline" disabled={Boolean(busy)} onClick={() => { try { localStorage.removeItem(storageKey); setLocalSave(false); setDraft(null); setStorageStatus('Локальный черновик удалён.'); } catch (error) { setStorageStatus(errorMessage(error)); } }}>Очистить локальный черновик</Button>}
                <details className="rounded-xl border p-3 text-xs"><summary className="cursor-pointer font-semibold">Исполнение и ограничения</summary><p className="mt-2 leading-5 text-muted-foreground">Shell, HTTP, Lua и действия ввода могут менять Android. Серверная проверка их не исполняет. Циклы ограничены таймаутом; retry требует идемпотентных действий. Видео и дерево UI Automator имеют независимые снимки, без покадровой синхронизации.</p></details>
              </div>}
          </div>
        </aside>}
    </div>
    <footer className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t bg-card px-4 py-2 text-[10px] text-muted-foreground"><span>DAG 1.0 · {nodes.length} шагов · {edges.length} связей {mode === 'source' ? '(последний применённый граф)' : ''}</span><span>Undo {history.length}/20 · {nodePending ? 'Параметры не применены' : currentReceipt ? 'Исходник проверен сервером' : 'Проверка структуры не выполнена'}</span></footer>
    {runOpen && editId && expectedVersion && <RunScriptModal open scriptId={editId} scriptName={document.name} expectedVersion={expectedVersion} requireVersion initialTargetMode="select" onClose={() => setRunOpen(false)} />}
  </section>;
}

function OwnedBuilder() {
  const editId = useSearchParams().get('id');
  const user = useAuthStore(state => state.user);
  const version = useAuthStore(state => state.sessionVersion);
  const key = user ? draftKey(user.org_id, user.id) : null;
  return <BuilderInner key={`${key}:${version}:${editId ?? 'new'}`} editId={editId} storageKey={key} />;
}
export default function ScriptBuilderPage() {
  return <Suspense fallback={<div role="status" className="p-6">Загружаем Script Studio…</div>}><OwnedBuilder /></Suspense>;
}
