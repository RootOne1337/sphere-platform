'use client';
import { useState, useEffect, useRef, Suspense } from 'react';
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState, addEdge, type Node, type Edge, type Connection, type ReactFlowInstance } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { ArrowLeft, Save, Check, Code2, Workflow, Undo2, Redo2, Download, Upload, Plus, Play, Search } from 'lucide-react';
import { nodeTypes } from '@/lib/dag/nodeTypes';
import { exportDag, importDag, ACTION_TYPES, type DagMetadata } from '@/lib/dag/export';
import { ACTION_LABELS, arrangeNodes, boundedSource, byteLength, draftKey, formatDag, initialDag, insertAction, parseSource, pushHistory, readDraft, SOURCE_LIMIT, writeDraft, type StudioDocument } from '@/lib/dag/studio';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { RunScriptModal } from '@/components/sphere/RunScriptModal';

interface ValidationReceipt { schema_version: 1; dag_hash: string; node_count: number; scope: 'structure-routes-lua-safety'; device_execution_verified: false }
const importedInitial = importDag(initialDag);
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
  const [nodes, setNodes, onNodesChange] = useNodesState(arrangeNodes(importedInitial.nodes, importedInitial.edges, initialDag.entry_node));
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(importedInitial.edges);
  const [metadata, setMetadata] = useState<DagMetadata>(importedInitial.metadata);
  const [document, setDocument] = useState<StudioDocument>({ name: 'Новый сценарий', source: formatDag(initialDag) });
  const documentRef = useRef(document); documentRef.current = document;
  const [mode, setMode] = useState<'graph' | 'source'>('graph');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [nodeSource, setNodeSource] = useState('');
  const [nodePending, setNodePending] = useState(false);
  const [canvasError, setCanvasError] = useState('');
  const [errors, setErrors] = useState('');
  const [receipt, setReceipt] = useState<{ fingerprint: string; result: ValidationReceipt } | null>(null);
  const [busy, setBusy] = useState<'check' | 'save' | null>(null);
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>(editId ? 'loading' : 'ready');
  const [loadError, setLoadError] = useState('');
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [expectedVersion, setExpectedVersion] = useState<{ id: string; version: number; dag_hash: string | null } | null>(null);
  const [baseDocument, setBaseDocument] = useState<StudioDocument | null>(editId ? null : document);
  const [history, setHistory] = useState<StudioDocument[]>([]);
  const [future, setFuture] = useState<StudioDocument[]>([]);
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState<StudioDocument | null>(null);
  const [localSave, setLocalSave] = useState(false);
  const [storageStatus, setStorageStatus] = useState('');
  const [runOpen, setRunOpen] = useState(false);
  const request = useRef<AbortController | null>(null);
  const loaded = useRef(false);
  const canvas = useRef<ReactFlowInstance | null>(null);
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

  useEffect(() => { live.current = true; return () => { live.current = false; request.current?.abort(); }; }, []);
  useEffect(() => {
    if (!canRead && busy) request.current?.abort();
  }, [canRead, busy]);
  useEffect(() => {
    const before = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); };
    window.addEventListener('beforeunload', before);
    return () => window.removeEventListener('beforeunload', before);
  }, [dirty]);

  function syncGraph(next: StudioDocument) {
    const imported = importDag(parseSource(next.source));
    setNodes(arrangeNodes(imported.nodes, imported.edges, imported.metadata.entry_node));
    setEdges(imported.edges); setMetadata(imported.metadata); setCanvasError('');
  }
  function remember() { const before = documentRef.current; setHistory(old => pushHistory(old, before)); setFuture([]); }
  function changeDocument(next: StudioDocument, graph = false) {
    boundedSource(next.source);
    if (graph) syncGraph(next);
    remember(); setDocument(next); setReceipt(null); setErrors('');
  }
  function selectNode(node: Node) {
    if (nodePending) { setErrors('Примените или отмените параметры текущего шага перед выбором другого.'); return; }
    setSelectedId(node.id);
    try { setNodeSource(JSON.stringify(exportDag(nodes, edges, metadata).nodes.find(item => item.id === node.id), null, 2)); }
    catch (error) { setErrors(errorMessage(error)); }
  }
  function restoreHistory(direction: 'undo' | 'redo') {
    const stack = direction === 'undo' ? history : future;
    const next = stack.at(-1); if (!next) return;
    if (direction === 'undo') { setHistory(stack.slice(0, -1)); setFuture(old => pushHistory(old, document)); }
    else { setFuture(stack.slice(0, -1)); setHistory(old => pushHistory(old, document)); }
    setDocument(next); setMode('source'); setSelectedId(null); setNodePending(false); setReceipt(null); setErrors(''); setCanvasError('');
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
        setNodes(arrangeNodes(imported.nodes, imported.edges, imported.metadata.entry_node)); setEdges(imported.edges); setMetadata(imported.metadata);
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
    const handle = connection.sourceHandle ?? null;
    if (edges.some(edge => edge.source === connection.source && (edge.sourceHandle ?? null) === handle)) {
      setErrors('Этот выход уже соединён. Сначала удалите существующую связь.'); return;
    }
    const nextEdges = addEdge(connection, edges); setEdges(nextEdges); publishCanvas(nodes, nextEdges);
  };
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

  function addAction(type: typeof ACTION_TYPES[number]) {
    try {
      if (nodePending) throw new Error('Сначала примените параметры выбранного шага.');
      const id = `step_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`;
      const graph = insertAction(parseSource(document.source), type, id, selectedId ?? undefined);
      changeDocument({ ...document, source: formatDag(graph) }, true);
      setSelectedId(id); setNodeSource(JSON.stringify(graph.nodes.find(node => node.id === id), null, 2)); setMode('graph');
      window.requestAnimationFrame(() => { if (live.current) void canvas.current?.fitView({ padding: 0.2 }); });
    } catch (error) { setErrors(errorMessage(error)); }
  }
  function applyNode() {
    try {
      const graph = parseSource(document.source);
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
    if (!documentRef.current.name.trim() || documentRef.current.name.length > 255) throw new Error('Название сценария: 1–255 символов.');
    return dag;
  }
  async function checkOrSave(operation: 'check' | 'save') {
    if (inFlight.current || loadState !== 'ready' || !accessRef.current.can(operation === 'save' ? 'script:write' : 'script:read')) return;
    const submitted = documentRef.current;
    const sentFingerprint = JSON.stringify(submitted);
    const controller = new AbortController(); request.current = controller;
    try {
      const dag = getDraftDag();
      inFlight.current = true; setBusy(operation); setErrors('');
      if (operation === 'check') {
        const { data } = await api.post<ValidationReceipt>('/scripts/validate', { dag }, { signal: controller.signal });
        if (!live.current || controller.signal.aborted || JSON.stringify(documentRef.current) !== sentFingerprint || !accessRef.current.can('script:read')) return;
        if (data.schema_version !== 1 || data.scope !== 'structure-routes-lua-safety' || data.device_execution_verified !== false
          || !/^[a-f0-9]{64}$/.test(data.dag_hash) || data.node_count !== dag.nodes.length) throw new Error('Ответ проверки не соответствует контракту.');
        setReceipt({ fingerprint: sentFingerprint, result: data });
      } else {
        if (editId) {
          if (!expectedVersion?.id) throw new Error('Версия неизвестна. Откройте актуальный сценарий из каталога.');
          await api.put(`/scripts/${editId}`, { name: submitted.name.trim(), dag, expected_current_version_id: expectedVersion.id }, { signal: controller.signal });
        } else await api.post('/scripts', { name: submitted.name.trim(), dag }, { signal: controller.signal });
        if (!live.current || controller.signal.aborted || !accessRef.current.can('script:write')) return;
        await queryClient.invalidateQueries({ queryKey: ['scripts'] });
        if (live.current) { setBaseDocument(submitted); router.push('/scripts'); }
      }
    } catch (error) { if (live.current && !controller.signal.aborted) setErrors(errorMessage(error)); }
    finally { inFlight.current = false; if (live.current) setBusy(null); }
  }
  async function importFile(file: File | undefined) {
    if (!file) return;
    try {
      if (file.size > SOURCE_LIMIT) throw new Error('Файл превышает 512 KiB.');
      const source = boundedSource(await file.text());
      if (!live.current || !accessRef.current.can('script:write')) return;
      // Invalid source is retained for repair; it cannot publish the old graph.
      changeDocument({ ...documentRef.current, source }); setMode('source'); setSelectedId(null); setNodePending(false);
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
      setMode(nextMode); setErrors(''); setSelectedId(null);
    } catch (error) { setErrors(errorMessage(error)); }
  }
  function leave() {
    if (!dirty || window.confirm('Есть несохранённые изменения. Выйти из редактора?')) router.push('/scripts');
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
  return <section aria-label="Script Studio" className="flex min-h-[600px] min-w-0 flex-col bg-background lg:h-[calc(100dvh-4rem)] lg:min-h-0">
    <header className="shrink-0 space-y-3 border-b p-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="icon" aria-label="К каталогу сценариев" onClick={leave}><ArrowLeft className="size-4" /></Button>
        <div className="min-w-0 flex-1"><p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Автоматизация / Script Studio</p>
          <label className="sr-only" htmlFor="studio-name">Название сценария</label>
          <Input id="studio-name" className="mt-1 max-w-md font-semibold" maxLength={255} value={document.name} disabled={!writable}
            onChange={event => changeDocument({ ...document, name: event.target.value })} /></div>
        <span className="rounded-full border px-3 py-1 text-xs">{editId ? 'Новая версия существующего' : 'Новый сценарий'} · {dirty ? 'Есть изменения' : 'Без изменений'}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border p-1" role="group" aria-label="Представление сценария">
          <Button size="sm" variant={mode === 'graph' ? 'secondary' : 'ghost'} aria-pressed={mode === 'graph'} onClick={() => switchMode('graph')}><Workflow className="mr-2 size-4" />Граф</Button>
          <Button size="sm" variant={mode === 'source' ? 'secondary' : 'ghost'} aria-pressed={mode === 'source'} onClick={() => switchMode('source')}><Code2 className="mr-2 size-4" />JSON</Button>
        </div>
        <Button variant="outline" size="icon" aria-label="Отменить изменение" disabled={!writable || !history.length} onClick={() => restoreHistory('undo')}><Undo2 className="size-4" /></Button>
        <Button variant="outline" size="icon" aria-label="Повторить изменение" disabled={!writable || !future.length} onClick={() => restoreHistory('redo')}><Redo2 className="size-4" /></Button>
        <Button size="sm" variant="outline" disabled={!writable || nodePending} onClick={() => fileInput.current?.click()}><Upload className="mr-2 size-4" />Импорт JSON</Button>
        <input ref={fileInput} type="file" accept=".json,application/json" className="hidden" aria-label="Файл сценария" onChange={event => { void importFile(event.target.files?.[0]); event.target.value = ''; }} />
        <Button size="sm" variant="outline" onClick={exportFile}><Download className="mr-2 size-4" />Экспорт</Button>
        {mode === 'graph' && <Button size="sm" variant="ghost" disabled={Boolean(busy) || nodePending} onClick={() => { setNodes(arrangeNodes(nodes, edges, metadata.entry_node)); window.requestAnimationFrame(() => { if (live.current) void canvas.current?.fitView({ padding: 0.2 }); }); }}>Упорядочить</Button>}
        <div className="hidden flex-1 lg:block" />
        <Button size="sm" variant="outline" disabled={Boolean(busy) || nodePending || Boolean(canvasError)} onClick={() => void checkOrSave('check')}><Check className="mr-2 size-4" />{busy === 'check' ? 'Проверяем…' : 'Проверить на сервере'}</Button>
        <Button size="sm" disabled={!writable || nodePending || Boolean(canvasError)} onClick={() => void checkOrSave('save')}><Save className="mr-2 size-4" />{busy === 'save' ? 'Сохраняем…' : editId ? 'Сохранить версию' : 'Создать сценарий'}</Button>
        <Button size="sm" variant="outline" disabled={!canRun || Boolean(busy)} onClick={() => setRunOpen(true)} title="Запуск доступен для сохранённой неизменённой версии"><Play className="mr-2 size-4" />Запустить версию</Button>
      </div>
      {!canWrite && <p role="status" className="text-sm text-muted-foreground">Исходник доступен для чтения и проверки. Права записи не подтверждены.</p>}
    </header>
    {(errors || canvasError) && <div role="alert" className="max-h-36 shrink-0 overflow-auto whitespace-pre-wrap border-b border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{errors || canvasError}</div>}
    {currentReceipt && <div role="status" className="shrink-0 border-b bg-emerald-500/10 px-4 py-2 text-sm">Структура, переходы и безопасность Lua проверены · {currentReceipt.node_count} шагов <span className="font-mono" title={currentReceipt.dag_hash}>· SHA256 {currentReceipt.dag_hash.slice(0, 12)}</span>. Выполнение на Android не проверялось.</div>}
    {draft && <div className="flex shrink-0 flex-wrap items-center gap-2 border-b bg-amber-500/10 px-4 py-2 text-sm"><span>Найден локальный черновик этого сценария.</span>
      <Button size="sm" variant="outline" disabled={!writable} onClick={() => { try { changeDocument(draft); setMode('source'); setNodePending(false); setSelectedId(null); setDraft(null); } catch (error) { setErrors(errorMessage(error)); } }}>Восстановить черновик</Button>
      <Button size="sm" variant="ghost" onClick={() => { try { if (storageKey) localStorage.removeItem(storageKey); setDraft(null); } catch (error) { setStorageStatus(errorMessage(error)); } }}>Удалить черновик</Button></div>}
    <div className="flex min-h-0 min-w-0 flex-col lg:flex-1 lg:flex-row">
      <aside aria-label="Каталог действий" className="flex max-h-64 shrink-0 flex-col border-b bg-card lg:max-h-none lg:w-60 lg:border-b-0 lg:border-r">
        <div className="space-y-2 p-3"><h2 className="text-sm font-semibold">Действия <span className="text-muted-foreground">{ACTION_TYPES.length}</span></h2>
          <div className="relative"><Search className="absolute left-2 top-3 size-4 text-muted-foreground" /><Input className="pl-8" aria-label="Поиск действия" value={search} onChange={event => setSearch(event.target.value)} /></div>
          <p className="text-xs text-muted-foreground">Добавление после выбранного шага или перед завершением. Шаблоны требуют настройки под устройство.</p></div>
        <div className="min-h-0 flex-1 overflow-auto px-2 pb-3">{available.map(type => <button key={type} type="button" disabled={!writable || mode !== 'graph' || nodePending}
          className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left hover:bg-muted disabled:opacity-40" onClick={() => addAction(type)}>
          <Plus className="size-3 shrink-0" /><span className="min-w-0"><span className="block text-xs font-medium">{ACTION_LABELS[type]}</span><span className="block font-mono text-[11px] text-muted-foreground">{type}</span></span></button>)}
          {!available.length && <p className="p-2 text-sm text-muted-foreground">Действия не найдены.</p>}</div>
      </aside>
      <div className="relative h-[380px] min-w-0 flex-none lg:h-auto lg:min-h-0 lg:flex-1">
        {mode === 'source' ? <div className="flex h-full min-h-[380px] flex-col p-4 lg:min-h-0">
          <label htmlFor="studio-source" className="mb-2 text-sm font-medium">Исходник DAG 1.0 · {byteLength(document.source).toLocaleString('ru-RU')} байт / 512 KiB</label>
          <textarea id="studio-source" spellCheck={false} className="min-h-[280px] flex-1 resize-none rounded-lg border bg-card p-3 font-mono text-xs leading-5 outline-none focus:ring-2 focus:ring-ring" value={document.source} readOnly={!writable}
            onChange={event => { try { changeDocument({ ...document, source: event.target.value }); } catch (error) { setErrors(errorMessage(error)); } }} />
          <p className="mt-2 text-xs text-muted-foreground">Неверный JSON остаётся здесь. «Граф» применяет исходник атомарно. Сохранение проверяет текущий текст, а не прежний граф.</p>
        </div> : <ReactFlow nodes={nodes} edges={edges} onNodesChange={writable && !nodePending ? onNodesChange : undefined} onEdgesChange={writable && !nodePending ? onEdgesChange : undefined}
          onConnect={onConnect} onNodeClick={(_, node) => selectNode(node)} nodeTypes={nodeTypes} fitView nodesDraggable={writable && !nodePending} nodesConnectable={writable && !nodePending} deleteKeyCode={writable && !nodePending ? ['Backspace', 'Delete'] : null}
          onInit={instance => { canvas.current = instance; }} className="sphere-studio-flow"><Background gap={24} /><Controls /><MiniMap className="!hidden xl:!block" style={{ width: 120, height: 80 }} pannable zoomable /></ReactFlow>}
      </div>
      <aside aria-label="Параметры шага" className="flex min-h-0 shrink-0 flex-col border-t bg-card lg:w-[340px] lg:border-l lg:border-t-0 xl:w-[380px]">
        <div className="border-b p-4"><h2 className="text-sm font-semibold">{selectedNode ? ACTION_LABELS[(selectedNode.data.action as { type: typeof ACTION_TYPES[number] }).type] : 'Параметры и проверка'}</h2>
          <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{selectedId ?? 'Выберите шаг на графе'}</p></div>
        <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
          {selectedNode && mode === 'graph' ? <>
            <label htmlFor="studio-node" className="block text-xs font-medium">Шаг JSON: action, переходы, retry, timeout_ms</label>
            <textarea id="studio-node" spellCheck={false} className="h-72 w-full resize-y rounded-lg border bg-background p-3 font-mono text-xs leading-5 focus:outline-none focus:ring-2 focus:ring-ring" value={nodeSource} readOnly={!writable}
              onChange={event => { try { setNodeSource(boundedSource(event.target.value)); setNodePending(true); setReceipt(null); } catch (error) { setErrors(errorMessage(error)); } }} />
            <div className="flex flex-wrap gap-2"><Button size="sm" disabled={!writable || !nodePending} onClick={applyNode}>Применить параметры</Button>
              <Button size="sm" variant="outline" disabled={!nodePending || Boolean(busy)} onClick={() => { setNodePending(false); setNodeSource(JSON.stringify(parseSource(document.source).nodes.find(node => node.id === selectedId), null, 2)); setErrors(''); }}>Отменить параметры</Button></div>
            <p className="text-xs text-muted-foreground">ID ссылок: {nodes.map(node => node.id).join(', ')}. В condition используются action.on_true и action.on_false. Повторы могут повторить побочные эффекты.</p>
          </> : <div className="space-y-3 text-sm text-muted-foreground"><p>Граф и исходник описывают один сценарий. Здесь можно редактировать все параметры каждого шага, включая вложенные селекторы и HTTP-заголовки.</p>
            <p>Проверка сервера не гарантирует наличие элементов, root-доступ, разрешения и поддержку действий конкретной установленной версией APK.</p>
            <p>Запись с устройства и replay ещё не подключены. Запуск выполняет только сохранённую версию через обычное задание.</p></div>}
          <details className="rounded-lg border p-3 text-xs"><summary className="cursor-pointer font-medium">Границы и безопасность исполнения</summary><p className="mt-2 text-muted-foreground">shell, HTTP, Lua, очистка данных и действия ввода могут менять устройство. Добавление и серверная проверка не исполняют их. Таймаут графа ограничивает циклы; retry требует идемпотентных действий.</p></details>
          <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={localSave} disabled={!writable || !storageKey} onChange={event => setLocalSave(event.target.checked)} /><span>Сохранять полный исходник на этом ПК<br /><span className="text-muted-foreground">Один черновик на пользователя, до 512 KiB, срок восстановления 7 дней. Может содержать приватный текст и код. Параметры шага сначала примените.</span></span></label>
          {storageStatus && <p role="status" className="text-xs text-muted-foreground">{storageStatus}</p>}
          {storageKey && <Button size="sm" variant="ghost" disabled={Boolean(busy)} onClick={() => { try { localStorage.removeItem(storageKey); setLocalSave(false); setDraft(null); setStorageStatus('Локальный черновик удалён.'); } catch (error) { setStorageStatus(errorMessage(error)); } }}>Очистить локальный черновик</Button>}
        </div>
      </aside>
    </div>
    <footer className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t bg-card px-4 py-2 text-xs text-muted-foreground">
      <span>DAG 1.0 · {nodes.length} шагов · {edges.length} связей {mode === 'source' ? '(последний применённый граф)' : ''}</span>
      <span>Undo {history.length}/{20} · до 2 MiB на стек</span><span>{expectedVersion ? `Базовая версия ${expectedVersion.version || expectedVersion.id.slice(0, 8)}` : 'Ещё не опубликован'}</span>
      <span>{nodePending ? 'Есть неприменённые параметры' : currentReceipt ? 'Проверка относится к текущему исходнику' : 'Текущий исходник не проверен сервером'}</span>
    </footer>
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
