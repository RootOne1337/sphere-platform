'use client';
import { useState, useCallback } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { nodeTypes } from '@/lib/dag/nodeTypes';
import { exportDag, validateDag } from '@/lib/dag/export';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { useRouter } from 'next/navigation';

const INITIAL_NODES = [
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

function getDefaultData(type: string) {
  const defaults: Record<string, object> = {
    Tap: { type: 'Tap', x: 540, y: 960 },
    Swipe: { type: 'Swipe', x1: 100, y1: 500, x2: 900, y2: 500, duration_ms: 300 },
    Sleep: { type: 'Sleep', duration_ms: 1000 },
    Lua: { type: 'Lua', code: '-- write Lua code here\nreturn true' },
    Condition: { type: 'Condition', condition_expr: 'ctx["prev"] == true' },
    Screenshot: { type: 'Screenshot', save_to_results: true },
  };
  return defaults[type] ?? { type };
}

export default function ScriptBuilderPage() {
  const router = useRouter();
  const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [scriptName, setScriptName] = useState('New Script');
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges],
  );

  const addNode = useCallback(
    (type: string) => {
      const newNode = {
        id: `${type.toLowerCase()}-${Date.now()}`,
        type,
        position: { x: 200, y: 200 },
        data: getDefaultData(type),
      };
      setNodes((ns) => [...ns, newNode]);
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
      await api.post('/scripts', { name: scriptName, dag });
      router.push('/scripts');
    } catch (e: unknown) {
      setErrors([(e as Error).message]);
    } finally {
      setSaving(false);
    }
  };

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
            {saving ? 'Saving…' : 'Save Script'}
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

      {/* React Flow canvas */}
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
    </div>
  );
}
