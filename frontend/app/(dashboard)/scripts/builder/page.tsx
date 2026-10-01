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
import { exportDag, validateDag, type DagExport } from '@/lib/dag/export';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { api } from '@/lib/api';
import { useRouter, useSearchParams } from 'next/navigation';
import { X, Save, Plus, ArrowLeft, Settings2, PlayCircle, MousePointer2, Smartphone, TerminalSquare, Eye, Fingerprint, GripHorizontal } from 'lucide-react';
import Editor from '@monaco-editor/react';

const INITIAL_NODES: Node[] = [
  {
    id: 'start-1',
    type: 'Start',
    position: { x: 200, y: 50 },
    data: { type: 'Start' },
  },
  {
    id: 'end-1',
    type: 'End',
    position: { x: 200, y: 400 },
    data: { type: 'End' },
  },
];

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
    Tap: { type: 'Tap', x: 540, y: 960 },
    Swipe: { type: 'Swipe', x1: 100, y1: 500, x2: 900, y2: 500, duration_ms: 300 },
    Sleep: { type: 'Sleep', duration_ms: 1000 },
    Lua: { type: 'Lua', code: '-- write Lua code here\nreturn true' },
    Condition: { type: 'Condition', condition_expr: 'ctx["prev"] == true' },
    Screenshot: { type: 'Screenshot', save_to_results: true },
  };
  return defaults[type] ?? { type };
}

function importDag(dag: DagExport): { nodes: Node[]; edges: Edge[] } {
  if (!dag || typeof dag !== 'object' || !dag.nodes || Array.isArray(dag.nodes)
    || typeof dag.entry_node !== 'string' || !dag.nodes[dag.entry_node]) {
    throw new Error('Сервер не вернул корректный граф сценария. Запись заблокирована.');
  }
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const ids = Object.keys(dag.nodes);

  ids.forEach((id, index) => {
    const raw = dag.nodes[id];
    const { type, links, ...rest } = raw;
    nodes.push({
      id,
      type,
      position: { x: 200, y: 50 + index * 120 },
      data: { type, ...rest },
    });
    for (const [handle, targetId] of Object.entries(links)) {
      edges.push({
        id: `e-${id}-${targetId}-${handle}`,
        source: id,
        target: targetId,
        sourceHandle: handle === 'next' ? null : handle,
      });
    }
  });

  return { nodes, edges };
}

/* ── Node Property Sidebar ─────────────────────────────────────────────── */
interface NodeSidebarProps {
  node: Node;
  onUpdate: (id: string, data: Record<string, unknown>) => void;
  onClose: () => void;
}

function NodeSidebar({ node, onUpdate, onClose }: NodeSidebarProps) {
  const d = node.data as Record<string, unknown>;
  const nodeType = d.type as string;

  const set = (key: string, value: unknown) => {
    onUpdate(node.id, { ...d, [key]: value });
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
            {numField('Wait Duration (ms)', 'duration_ms')}
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

        {nodeType === 'Condition' && (
          <div className="space-y-1.5">
            <Label className="text-[10px] uppercase font-bold tracking-widest text-[#555]">Eval Expression</Label>
            <Input
              value={String(d.condition_expr ?? '')}
              onChange={(e) => set('condition_expr', e.target.value)}
              className="h-8 text-xs font-mono bg-muted border-border focus-visible:border-primary rounded-sm text-cyan-300"
              placeholder="e.g. ctx['prev'] == true"
            />
          </div>
        )}

        {nodeType === 'Screenshot' && (
          <div className="flex justify-between items-center bg-muted p-3 border border-border rounded-sm">
            <Label className="text-[10px] uppercase font-bold tracking-widest text-foreground">Retain Artifacts</Label>
            <input
              type="checkbox"
              checked={Boolean(d.save_to_results)}
              onChange={(e) => set('save_to_results', e.target.checked)}
              className="w-4 h-4 bg-transparent border-[#555] checked:bg-primary rounded-sm"
            />
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Builder Inner ─────────────────────────────────────────────── */
function BuilderInner({ editId }: { editId: string | null }) {
  const router = useRouter();

  const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
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
        const { nodes: imported, edges: importedEdges } = importDag(dag);
        setScriptName(data.name ?? 'UNTITLED_SCRIPT');
        setNodes(imported);
        setEdges(importedEdges);
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
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges],
  );

  const addNode = useCallback(
    (type: string) => {
      const newNode: Node = {
        id: `${type.toLowerCase()}-${Date.now().toString().slice(-6)}`,
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
      const dag = exportDag(nodes, edges);
      const validationErrors = validateDag(dag);
      if (validationErrors.length > 0) {
        setErrors(validationErrors);
        return;
      }
      setErrors([]);
      saveInFlight.current = true;
      setSaving(true);
      if (editId) {
        await api.put(`/scripts/${editId}`, { name: scriptName, dag });
      } else {
        await api.post('/scripts', { name: scriptName, dag });
      }
      if (mounted.current) router.push('/scripts');
    } catch (e: unknown) {
      if (mounted.current) setErrors([(e as Error).message]);
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
            {saving ? 'COMMITING...' : editId ? 'UPDATE DAG' : 'DEPLOY DAG'}
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
