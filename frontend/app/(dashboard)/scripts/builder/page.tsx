'use client';
import { useState, useCallback, useEffect, Suspense } from 'react';
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
function BuilderInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const editId = searchParams.get('id');

  const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [scriptName, setScriptName] = useState('NOC_SCRIPT_DEF');
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [loaded, setLoaded] = useState(!editId);

  // Load existing script
  useEffect(() => {
    if (!editId) return;
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get(`/scripts/${editId}?include_dag=true`);
        if (cancelled) return;
        setScriptName(data.name ?? 'UNTITLED_SCRIPT');
        const dag = data.current_version?.dag ?? data.dag;
        if (dag) {
          const { nodes: imported, edges: importedEdges } = importDag(dag);
          setNodes(imported);
          setEdges(importedEdges);
        }
      } catch {
        setErrors(['[ERR] Failed to pull script payload from server']);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [editId, setNodes, setEdges]);

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
    try {
      const dag = exportDag(nodes, edges);
      const validationErrors = validateDag(dag);
      if (validationErrors.length > 0) {
        setErrors(validationErrors);
        return;
      }
      setErrors([]);
      setSaving(true);
      if (editId) {
        await api.put(`/scripts/${editId}`, { name: scriptName, dag });
      } else {
        await api.post('/scripts', { name: scriptName, dag });
      }
      router.push('/scripts');
    } catch (e: unknown) {
      setErrors([(e as Error).message]);
    } finally {
      setSaving(false);
    }
  };

  if (!loaded) {
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

          <Button variant="noc" onClick={handleSave} disabled={saving} className="h-8 px-6">
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

export default function ScriptBuilderPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center h-screen bg-card">
        <Fingerprint className="w-8 h-8 text-primary animate-pulse" />
      </div>
    }>
      <BuilderInner />
    </Suspense>
  );
}
