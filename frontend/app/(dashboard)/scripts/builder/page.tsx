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
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { api } from '@/lib/api';
import { useRouter, useSearchParams } from 'next/navigation';
import { X } from 'lucide-react';

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

const NODE_TYPES_LIST = ['Tap', 'Swipe', 'Sleep', 'Lua', 'Condition', 'Screenshot'] as const;

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

/** Reconstruct ReactFlow nodes/edges from a backend DAG */
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
    <div className="space-y-1" key={key}>
      <Label className="text-xs">{label}</Label>
      <Input
        type="number"
        value={Number(d[key] ?? 0)}
        onChange={(e) => set(key, Number(e.target.value))}
        className="h-8 text-sm"
      />
    </div>
  );

  return (
    <div className="w-72 border-l bg-background p-4 space-y-4 overflow-y-auto">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-sm">{nodeType} Properties</h3>
        <Button size="icon" variant="ghost" className="h-6 w-6" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">ID: {node.id}</p>

      {nodeType === 'Tap' && (
        <div className="space-y-3">
          {numField('X', 'x')}
          {numField('Y', 'y')}
          <div className="space-y-1">
            <Label className="text-xs">Description</Label>
            <Input
              value={String(d.description ?? '')}
              onChange={(e) => set('description', e.target.value)}
              className="h-8 text-sm"
            />
          </div>
        </div>
      )}

      {nodeType === 'Swipe' && (
        <div className="grid grid-cols-2 gap-2">
          {numField('X1', 'x1')}
          {numField('Y1', 'y1')}
          {numField('X2', 'x2')}
          {numField('Y2', 'y2')}
          <div className="col-span-2">{numField('Duration (ms)', 'duration_ms')}</div>
        </div>
      )}

      {nodeType === 'Sleep' && numField('Duration (ms)', 'duration_ms')}

      {nodeType === 'Lua' && (
        <div className="space-y-1">
          <Label className="text-xs">Lua Code</Label>
          <textarea
            value={String(d.code ?? '')}
            onChange={(e) => set('code', e.target.value)}
            rows={10}
            className="w-full rounded border bg-background p-2 text-xs font-mono resize-y"
          />
        </div>
      )}

      {nodeType === 'Condition' && (
        <div className="space-y-1">
          <Label className="text-xs">Expression</Label>
          <Input
            value={String(d.condition_expr ?? '')}
            onChange={(e) => set('condition_expr', e.target.value)}
            className="h-8 text-sm font-mono"
          />
        </div>
      )}

      {nodeType === 'Screenshot' && (
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={Boolean(d.save_to_results)}
            onChange={(e) => set('save_to_results', e.target.checked)}
          />
          <Label className="text-xs">Save to Results</Label>
        </div>
      )}
    </div>
  );
}

/* ── Builder Inner (needs useSearchParams inside Suspense) ─────────────── */
function BuilderInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const editId = searchParams.get('id');

  const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [scriptName, setScriptName] = useState('New Script');
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
        setScriptName(data.name ?? 'Untitled');
        const dag = data.current_version?.dag ?? data.dag;
        if (dag) {
          const { nodes: imported, edges: importedEdges } = importDag(dag);
          setNodes(imported);
          setEdges(importedEdges);
        }
      } catch {
        setErrors(['Failed to load script']);
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
        id: `${type.toLowerCase()}-${Date.now()}`,
        type,
        position: { x: 200, y: 200 },
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
    return <div className="flex items-center justify-center h-screen text-muted-foreground">Loading script…</div>;
  }

  return (
    <div className="h-screen flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between p-4 border-b gap-2 flex-wrap">
        <input
          value={scriptName}
          onChange={(e) => setScriptName(e.target.value)}
          className="text-lg font-bold bg-transparent border-b border-transparent hover:border-gray-500 focus:border-primary outline-none"
        />
        <div className="flex gap-2 flex-wrap">
          {NODE_TYPES_LIST.map((type) => (
            <Button key={type} size="sm" variant="outline" onClick={() => addNode(type)}>
              + {type}
            </Button>
          ))}
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : editId ? 'Update Script' : 'Save Script'}
          </Button>
        </div>
      </div>

      {/* Validation errors */}
      {errors.length > 0 && (
        <div className="bg-red-950 border-b border-red-800 p-3">
          {errors.map((e, i) => (
            <p key={i} className="text-sm text-red-400">
              {e}
            </p>
          ))}
        </div>
      )}

      {/* React Flow canvas + sidebar */}
      <div className="flex-1 flex">
        <div className="flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            nodeTypes={nodeTypes}
            fitView
          >
            <Background />
            <Controls />
            <MiniMap />
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
    <Suspense fallback={<div className="flex items-center justify-center h-screen text-muted-foreground">Loading…</div>}>
      <BuilderInner />
    </Suspense>
  );
}
