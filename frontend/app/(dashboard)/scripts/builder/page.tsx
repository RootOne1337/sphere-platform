'use client';
import { useState, useCallback, useEffect, useRef, Suspense } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { nodeTypes } from '@/lib/dag/nodeTypes';
import { exportDag, importDag, validateDag, type DagMetadata } from '@/lib/dag/export';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { api } from '@/lib/api';
import { useRouter, useSearchParams } from 'next/navigation';
import { X, Save, Plus, ArrowLeft, Settings2, PlayCircle, MousePointer2, Smartphone, TerminalSquare, Eye, Fingerprint, GripHorizontal } from 'lucide-react';
import Editor from '@monaco-editor/react';
import { isAxiosError } from 'axios';
import { useQueryClient } from '@tanstack/react-query';

const INITIAL_NODES: Node[] = [
  {
    id: 'start-1',
    type: 'Start',
    position: { x: 200, y: 50 },
    data: { type: 'Start', action: { type: 'start' } },
  },
  {
    id: 'end-1',
    type: 'End',
    position: { x: 200, y: 400 },
    data: { type: 'End', action: { type: 'end' } },
  },
];
const INITIAL_EDGES: Edge[] = [{ id: 'start-end', source: 'start-1', target: 'end-1' }];

const NODE_TYPES_LIST = [
  { type: 'Tap', icon: <MousePointer2 className="w-4 h-4" /> },
  { type: 'Swipe', icon: <GripHorizontal className="w-4 h-4" /> },
  { type: 'Sleep', icon: <PlayCircle className="w-4 h-4" /> },
  { type: 'Lua', icon: <TerminalSquare className="w-4 h-4" /> },
  { type: 'Condition', icon: <Settings2 className="w-4 h-4" /> },
  { type: 'Screenshot', icon: <Eye className="w-4 h-4" /> }
];

function getDefaultData(type: string): Record<string, unknown> {
  const defaults: Record<string, Record<string, unknown>> = {
    Tap: { type: 'tap', x: 540, y: 960 },
    Swipe: { type: 'swipe', x1: 100, y1: 500, x2: 900, y2: 500, duration_ms: 300 },
    Sleep: { type: 'sleep', ms: 1000 },
    Lua: { type: 'lua', code: '-- write Lua code here\nreturn true' },
    Condition: { type: 'condition', code: 'return ctx["prev"] == true' },
    Screenshot: { type: 'screenshot' },
  };
  return { type, action: defaults[type], retry: 0, timeout_ms: 30_000 };
}

/* ── Node Property Sidebar ─────────────────────────────────────────────── */
interface NodeSidebarProps {
  node: Node;
  onUpdate: (id: string, data: Record<string, unknown>) => void;
  onClose: () => void;
}

function NodeSidebar({ node, onUpdate, onClose }: NodeSidebarProps) {
  const d = node.data.action as Record<string, unknown>;
  const nodeType = node.type;

  const set = (key: string, value: unknown) => {
    onUpdate(node.id, { ...node.data, action: { ...d, [key]: value } });
  };

  const numField = (label: string, key: string) => (
    <div className="space-y-1.5" key={key}>
      <Label className="text-[10px] uppercase font-bold tracking-widest text-[#555]">{label}</Label>
      <Input
        type="number"
        value={Number(d[key] ?? 0)}
        onChange={(e) => set(key, Number(e.target.value))}
        className="h-8 text-xs font-mono bg-muted border-border focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary rounded-sm"
      />
    </div>
  );

  return (
    <div className="w-80 border-l border-border bg-card p-5 flex flex-col shadow-2xl z-20 transition-all duration-300 transform translate-x-0">
      <div className="flex items-center justify-between mb-6 pb-4 border-b border-border">
        <div className="flex items-center gap-2">
          <Settings2 className="w-4 h-4 text-primary" />
          <h3 className="font-bold text-xs uppercase tracking-widest text-foreground">{nodeType} Config</h3>
        </div>
        <Button size="icon" variant="ghost" className="h-6 w-6 hover:bg-secondary hover:text-white rounded-sm" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>
      </div>

      <div className="mb-6 bg-muted p-3 border border-border rounded-sm">
        <p className="text-[9px] uppercase text-muted-foreground tracking-widest mb-1">Node Identifier</p>
        <p className="text-xs font-mono text-primary truncate" title={node.id}>{node.id}</p>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar space-y-5 pr-1">
        {nodeType === 'Tap' && (
          <div className="grid grid-cols-2 gap-4">
            {numField('Coordinate X', 'x')}
            {numField('Coordinate Y', 'y')}
            <div className="col-span-2 space-y-1.5">
              <Label className="text-[10px] uppercase font-bold tracking-widest text-[#555]">Description</Label>
              <Input
                value={String(d.description ?? '')}
                onChange={(e) => set('description', e.target.value)}
                className="h-8 text-xs font-mono bg-muted border-border focus-visible:border-primary rounded-sm"
                placeholder="Optional tap desc..."
              />
            </div>
          </div>
        )}

        {nodeType === 'Swipe' && (
          <div className="grid grid-cols-2 gap-4">
            {numField('Start X1', 'x1')}
            {numField('Start Y1', 'y1')}
            {numField('End X2', 'x2')}
            {numField('End Y2', 'y2')}
            <div className="col-span-2">{numField('Travel Duration (ms)', 'duration_ms')}</div>
          </div>
        )}

        {nodeType === 'Sleep' && (
          <div className="space-y-4">
            {numField('Длительность паузы (мс)', 'ms')}
            <p className="text-[10px] text-[#555] font-mono leading-relaxed mt-2 px-1">
              Pauses script execution for the specified milliseconds. Useful for waiting out animations or network payload loads.
            </p>
          </div>
        )}

        {nodeType === 'Lua' && (
          <div className="space-y-1.5 flex flex-col h-[450px]">
            <Label className="text-[10px] uppercase font-bold tracking-widest text-[#555]">Lua Execution Block</Label>
            <div className="flex-1 rounded-sm border border-border overflow-hidden">
              <Editor
                height="100%"
                defaultLanguage="lua"
                theme="vs-dark"
                value={String(d.code ?? '')}
                onChange={(val) => set('code', val || '')}
                options={{
                  minimap: { enabled: false },
                  fontSize: 12,
                  fontFamily: '"JetBrains Mono", monospace',
                  lineNumbers: "on",
                  scrollBeyondLastLine: false,
                  wordWrap: "on",
                  padding: { top: 8, bottom: 8 }
                }}
              />
            </div>
          </div>
        )}

        {nodeType === 'Condition' && !d.check && (
          <div className="space-y-1.5">
            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Lua-код условия (return true / false)</Label>
            <Input
              value={String(d.code ?? '')}
              onChange={(e) => set('code', e.target.value)}
              className="h-8 text-xs font-mono bg-muted border-border focus-visible:border-primary rounded-sm text-cyan-300"
              placeholder="return ctx['prev'] == true"
            />
          </div>
        )}

        {nodeType === 'Screenshot' && (
          <div className="space-y-1.5">
            <Label className="text-xs">Переменная результата (необязательно)</Label>
            <Input
              value={String(d.save_to ?? '')}
              onChange={(e) => {
                const action = { ...d };
                if (e.target.value) action.save_to = e.target.value;
                else delete action.save_to;
                onUpdate(node.id, { ...node.data, action });
              }}
            />
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <label className="space-y-1 text-xs">Повторы
            <Input type="number" min={0} max={5} value={Number(node.data.retry ?? 0)}
              onChange={(e) => onUpdate(node.id, { ...node.data, retry: Number(e.target.value) })} />
          </label>
          <label className="space-y-1 text-xs">Таймаут (мс)
            <Input type="number" min={100} max={3600000} value={Number(node.data.timeout_ms ?? 30000)}
              onChange={(e) => onUpdate(node.id, { ...node.data, timeout_ms: Number(e.target.value) })} />
          </label>
        </div>
        <details className="rounded-lg border border-border p-3 text-xs" open={nodeType === 'Action' || Boolean(d.check)}>
          <summary className="cursor-pointer font-medium">Все параметры: {String(d.type)}</summary>
          <p className="mt-2 text-muted-foreground">Параметры сохраняются целиком. Переходы редактируются связями на графе.</p>
          <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all font-mono">{JSON.stringify(d, null, 2)}</pre>
        </details>
      </div>
    </div>
  );
}

/* ── Builder Inner ─────────────────────────────────────────────── */
function BuilderInner({ editId }: { editId: string | null }) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(INITIAL_EDGES);
  const [metadata, setMetadata] = useState<DagMetadata | undefined>();
  const [expectedVersionId, setExpectedVersionId] = useState<string | null>(null);
  const [scriptName, setScriptName] = useState('NOC_SCRIPT_DEF');
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>(editId ? 'loading' : 'ready');
  const [loadError, setLoadError] = useState('');
  const [loadAttempt, setLoadAttempt] = useState(0);
  const mounted = useRef(true);
  const saveInFlight = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  // Load existing script
  useEffect(() => {
    if (!editId) return;
    let cancelled = false;
    const controller = new AbortController();
    setLoadState('loading');
    setLoadError('');
    (async () => {
      try {
        const { data } = await api.get(`/scripts/${editId}?include_dag=true`, { signal: controller.signal });
        if (cancelled) return;
        if (data.id !== editId) throw new Error('Ответ относится к другому сценарию. Запись заблокирована.');
        const dag = data.current_version?.dag ?? data.dag;
        const { nodes: imported, edges: importedEdges, metadata: importedMetadata } = importDag(dag);
        const versionId = data.current_version_id ?? data.current_version?.id;
        if (typeof versionId !== 'string' || !versionId) throw new Error('Не получена версия сценария. Запись заблокирована.');
        if (data.is_archived) throw new Error('Архивный сценарий доступен только для чтения в каталоге.');
        setScriptName(data.name ?? 'UNTITLED_SCRIPT');
        setNodes(imported);
        setEdges(importedEdges);
        setMetadata(importedMetadata);
        setExpectedVersionId(versionId);
        setLoadState('ready');
      } catch (error) {
        if (cancelled) return;
        setLoadError(error instanceof Error ? error.message : 'Не удалось загрузить сценарий.');
        setLoadState('error');
      }
    })();
    return () => { cancelled = true; controller.abort(); };
  }, [editId, loadAttempt, setNodes, setEdges]);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => {
      const handle = params.sourceHandle ?? null;
      if (eds.some((edge) => edge.source === params.source && (edge.sourceHandle ?? null) === handle)) {
        setErrors(['Этот выход уже соединён. Сначала удалите существующую связь.']);
        return eds;
      }
      return addEdge(params, eds);
    }),
    [setEdges],
  );

  const addNode = useCallback(
    (type: string) => {
      const newNode: Node = {
        id: `${type.toLowerCase()}-${crypto.randomUUID()}`,
        type,
        position: { x: window.innerWidth / 2, y: window.innerHeight / 2 - 100 },
        data: getDefaultData(type),
      };
      setNodes((ns) => [...ns, newNode]);
    },
    [setNodes],
  );

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
  }, []);

  const updateNodeData = useCallback(
    (id: string, data: Record<string, unknown>) => {
      setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data } : n)));
      setSelectedNode((prev) => (prev?.id === id ? { ...prev, data } : prev));
    },
    [setNodes],
  );

  const handleSave = async () => {
    if (loadState !== 'ready' || saveInFlight.current) return;
    try {
      const dag = exportDag(nodes, edges, metadata);
      const validationErrors = validateDag(dag);
      if (validationErrors.length > 0) {
        setErrors(validationErrors);
        return;
      }
      setErrors([]);
      saveInFlight.current = true;
      setSaving(true);
      if (editId) {
        if (!expectedVersionId) throw new Error('Версия сценария неизвестна. Обновите страницу.');
        await api.put(`/scripts/${editId}`, { name: scriptName, dag, expected_current_version_id: expectedVersionId });
      } else {
        await api.post('/scripts', { name: scriptName, dag });
      }
      // The destination may still have a fresh cached catalog from before this
      // write. Mark all script projections stale before navigating back.
      await queryClient.invalidateQueries({ queryKey: ['scripts'] });
      if (mounted.current) router.push('/scripts');
    } catch (e: unknown) {
      if (mounted.current) setErrors([isAxiosError(e) && e.response?.status === 409
        ? 'Версия сценария изменилась или он архивирован. Сохранение отклонено. Скопируйте нужные изменения и заново откройте актуальную версию из каталога.'
        : e instanceof Error ? e.message : 'Не удалось сохранить сценарий.']);
    } finally {
      saveInFlight.current = false;
      if (mounted.current) setSaving(false);
    }
  };

  if (loadState === 'error') {
    return (
      <div className="mx-auto flex min-h-[50vh] max-w-xl items-center p-6">
        <div role="alert" className="w-full space-y-4 rounded-xl border border-destructive/30 bg-card p-6">
          <h1 className="text-lg font-semibold">Сценарий не загружен</h1>
          <p className="break-words text-sm text-muted-foreground">{loadError}</p>
          <p className="text-sm">Редактирование и сохранение недоступны до успешной загрузки исходного графа.</p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => setLoadAttempt((attempt) => attempt + 1)}>Повторить загрузку</Button>
            <Button variant="outline" onClick={() => router.push('/scripts')}>К каталогу сценариев</Button>
          </div>
        </div>
      </div>
    );
  }

  if (loadState === 'loading') {
    return (
      <div className="flex items-center justify-center h-screen bg-card">
        <div className="flex flex-col items-center">
          <Fingerprint className="w-8 h-8 text-primary animate-pulse mb-4" />
          <p className="text-xs font-mono font-bold tracking-widest text-[#555] uppercase animate-pulse">Initializing Workflow Canvas...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-card">
      {/* Heavy Duty Toolbar */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-muted z-10 shadow-xl shrink-0">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:bg-border hover:text-white" onClick={() => router.push('/scripts')}>
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <div className="flex flex-col">
            <span className="text-[9px] uppercase tracking-widest text-[#555] font-bold">Script Name</span>
            <input
              value={scriptName}
              onChange={(e) => setScriptName(e.target.value)}
              className="text-sm font-bold font-mono text-primary bg-transparent border-b border-transparent hover:border-border focus:border-primary outline-none transition-colors w-[250px]"
            />
          </div>
        </div>

        <div className="flex gap-2.5 items-center">
          <div className="flex gap-1.5 mr-4 border-r border-border pr-4">
            {NODE_TYPES_LIST.map(({ type, icon }) => (
              <Button key={type} size="sm" variant="outline" className="h-8 bg-[#151515] border-border hover:border-primary hover:text-primary px-2" onClick={() => addNode(type)} title={`Add ${type} Node`}>
                {icon}
              </Button>
            ))}
          </div>

          <Button variant="noc" onClick={handleSave} disabled={saving || loadState !== 'ready'} className="h-8 px-6">
            {saving ? 'Сохраняем…' : editId ? 'Сохранить версию' : 'Создать сценарий'}
            <Save className="w-3.5 h-3.5 ml-2" />
          </Button>
        </div>
      </div>

      {/* Validation Errors Console */}
      {errors.length > 0 && (
        <div className="bg-[#1A0505] border-b border-red-900/50 p-3 shrink-0">
          <p className="text-[10px] font-bold text-red-500 uppercase tracking-widest mb-1 items-center flex gap-2">
            <X className="w-3 h-3" /> DAG Compiler Exceptions
          </p>
          {errors.map((e, i) => (
            <p key={i} className="text-xs font-mono text-red-400 pl-5">
              &gt; {e}
            </p>
          ))}
        </div>
      )}

      {/* Canvas Area */}
      <div className="flex-1 flex overflow-hidden relative">
        <div className="flex-1 w-full h-full" style={{ background: '#0A0A0A' }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            nodeTypes={nodeTypes}
            fitView
            className="sphere-noc-flow"
          >
            <Background gap={24} color="#222" style={{ backgroundColor: '#050505' }} />
            <Controls className="react-flow__controls-noc" />
            <MiniMap
              nodeColor="#333"
              maskColor="rgba(0,0,0,0.8)"
              style={{ backgroundColor: '#111', border: '1px solid #333', borderRadius: '4px' }}
            />
          </ReactFlow>
        </div>
        {selectedNode && (
          <NodeSidebar
            node={selectedNode}
            onUpdate={updateNodeData}
            onClose={() => setSelectedNode(null)}
          />
        )}
      </div>
    </div>
  );
}

function OwnedBuilder() {
  const editId = useSearchParams().get('id');
  // A new resource owns its graph, errors and in-flight load independently.
  return <BuilderInner key={editId ?? 'new-script'} editId={editId} />;
}

export default function ScriptBuilderPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center h-screen bg-card">
        <Fingerprint className="w-8 h-8 text-primary animate-pulse" />
      </div>
    }>
      <OwnedBuilder />
    </Suspense>
  );
}
