# SPLIT-5 — Script Builder (Visual DAG Editor)

**ТЗ-родитель:** TZ-10-Web-Frontend  
**Ветка:** `stage/10-frontend`  
**Задача:** `SPHERE-055`  
**Исполнитель:** Frontend  
**Оценка:** 2 дня  
**Блокирует:** —
**Интеграция при merge:** TZ-11 Monitoring подключает frontend-алерты; работает независимо

---

## Цель Сплита

Визуальный редактор DAG-скриптов на основе React Flow: drag-and-drop нод, настройка параметров в сайдбаре, экспорт в JSON для бэкенда.

---

## Шаг 1 — Зависимости

```bash
npm install @xyflow/react
```

---

## Шаг 2 — Node Types для React Flow

```typescript
// lib/dag/nodeTypes.ts
import { NodeTypes } from '@xyflow/react';
import { TapNode } from '@/components/sphere/dag/TapNode';
import { SwipeNode } from '@/components/sphere/dag/SwipeNode';
import { SleepNode } from '@/components/sphere/dag/SleepNode';
import { LuaNode } from '@/components/sphere/dag/LuaNode';
import { ConditionNode } from '@/components/sphere/dag/ConditionNode';
import { StartNode } from '@/components/sphere/dag/StartNode';
import { EndNode } from '@/components/sphere/dag/EndNode';
import { ScreenshotNode } from '@/components/sphere/dag/ScreenshotNode';

export const nodeTypes: NodeTypes = {
    Tap: TapNode,
    Swipe: SwipeNode,
    Sleep: SleepNode,
    Lua: LuaNode,
    Condition: ConditionNode,
    Start: StartNode,
    End: EndNode,
    Screenshot: ScreenshotNode,
};

// DAG типы
export type DagNodeData = 
    | { type: 'Tap'; x: number; y: number; description?: string }
    | { type: 'Swipe'; x1: number; y1: number; x2: number; y2: number; duration_ms: number }
    | { type: 'Sleep'; duration_ms: number }
    | { type: 'Lua'; code: string }
    | { type: 'Condition'; condition_expr: string }
    | { type: 'Screenshot'; save_to_results: boolean }
    | { type: 'Start' }
    | { type: 'End' };
```

---

## Шаг 3 — TapNode компонент

```tsx
// components/sphere/dag/TapNode.tsx
import { Handle, Position, NodeProps } from '@xyflow/react';
import { MousePointerClick } from 'lucide-react';

export function TapNode({ data, selected }: NodeProps) {
    return (
        <div className={`rounded-lg border-2 p-3 bg-blue-950 min-w-32 text-center
            ${selected ? 'border-blue-400' : 'border-blue-700'}`}
        >
            <Handle type="target" position={Position.Top} />
            <div className="flex items-center gap-2 justify-center mb-1">
                <MousePointerClick className="w-4 h-4 text-blue-400" />
                <span className="text-sm font-medium text-blue-200">Tap</span>
            </div>
            <p className="text-xs text-blue-400">
                ({(data as any).x}, {(data as any).y})
            </p>
            {(data as any).description && (
                <p className="text-xs text-gray-500 mt-1 truncate">{(data as any).description as string}</p>
            )}
            <Handle type="source" position={Position.Bottom} />
        </div>
    );
}
```

---

## Шаг 4 — DAG Export (Flow → JSON)

```typescript
// lib/dag/export.ts
import { Node, Edge } from '@xyflow/react';

export interface DagExport {
    entry_node: string;
    nodes: Record<string, {
        type: string;
        links: Record<string, string>;
        [key: string]: unknown;
    }>;
}

export function exportDag(nodes: Node[], edges: Edge[]): DagExport {
    if (nodes.length === 0) throw new Error('DAG is empty');
    
    const startNode = nodes.find(n => n.type === 'Start');
    if (!startNode) throw new Error('DAG must have a Start node');
    
    // Построить карту связей
    const linksMap: Record<string, Record<string, string>> = {};
    
    for (const edge of edges) {
        if (!linksMap[edge.source]) linksMap[edge.source] = {};
        // sourceHandle: 'next', 'true_branch', 'false_branch'
        const handleKey = edge.sourceHandle ?? 'next';
        linksMap[edge.source][handleKey] = edge.target;
    }
    
    // Сериализация нод
    const exportNodes: DagExport['nodes'] = {};
    
    for (const node of nodes) {
        const { type, id, data } = node;
        if (!type) continue;
        
        exportNodes[id] = {
            type,
            links: linksMap[id] ?? {},
            ...data,
        };
    }
    
    return {
        entry_node: startNode.id,
        nodes: exportNodes,
    };
}

export function validateDag(dag: DagExport): string[] {
    const errors: string[] = [];
    const nodeIds = new Set(Object.keys(dag.nodes));
    
    // Все ссылки должны указывать на существующие ноды
    for (const [id, node] of Object.entries(dag.nodes)) {
        for (const [handle, targetId] of Object.entries(node.links)) {
            if (!nodeIds.has(targetId)) {
                errors.push(`Node "${id}" link "${handle}" → unknown node "${targetId}"`);
            }
        }
    }
    
    // End ноды должны существовать
    const hasEnd = Object.values(dag.nodes).some(n => n.type === 'End');
    if (!hasEnd) errors.push('DAG must have at least one End node');
    
    return errors;
}
```

---

## Шаг 5 — Script Builder Page

```tsx
// app/(dashboard)/scripts/builder/page.tsx
'use client';
import { useState, useCallback } from 'react';
import {
    ReactFlow, Background, Controls, MiniMap,
    useNodesState, useEdgesState, addEdge,
    Connection,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { nodeTypes } from '@/lib/dag/nodeTypes';
import { exportDag, validateDag } from '@/lib/dag/export';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { useRouter } from 'next/navigation';

const INITIAL_NODES = [
    { id: 'start-1', type: 'Start', position: { x: 200, y: 50 }, data: { type: 'Start' } },
    { id: 'end-1', type: 'End', position: { x: 200, y: 400 }, data: { type: 'End' } },
];

export default function ScriptBuilderPage() {
    const router = useRouter();
    const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [scriptName, setScriptName] = useState('New Script');
    const [saving, setSaving] = useState(false);
    const [errors, setErrors] = useState<string[]>([]);
    
    const onConnect = useCallback(
        (params: Connection) => setEdges(eds => addEdge(params, eds)),
        [setEdges]
    );
    
    const addNode = useCallback((type: string) => {
        const newNode = {
            id: `${type.toLowerCase()}-${Date.now()}`,
            type,
            position: { x: 200, y: 200 },
            data: getDefaultData(type),
        };
        setNodes(ns => [...ns, newNode]);
    }, [setNodes]);
    
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
            <div className="flex items-center justify-between p-4 border-b">
                <input
                    value={scriptName}
                    onChange={e => setScriptName(e.target.value)}
                    className="text-lg font-bold bg-transparent border-b border-transparent hover:border-gray-500 focus:border-primary outline-none"
                />
                <div className="flex gap-2">
                    {['Tap', 'Swipe', 'Sleep', 'Lua', 'Condition', 'Screenshot'].map(type => (
                        <Button key={type} size="sm" variant="outline" onClick={() => addNode(type)}>
                            + {type}
                        </Button>
                    ))}
                    <Button onClick={handleSave} disabled={saving}>
                        {saving ? 'Saving…' : 'Save Script'}
                    </Button>
                </div>
            </div>
            
            {errors.length > 0 && (
                <div className="bg-red-950 border-b border-red-800 p-3">
                    {errors.map((e, i) => <p key={i} className="text-sm text-red-400">{e}</p>)}
                </div>
            )}
            
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
```

---

## Критерии готовности

- [ ] Drag-and-drop нод на холсте
- [ ] Соединение нод через handles (source → target)
- [ ] `exportDag()` строит правильный JSON со всеми links
- [ ] `validateDag()` возвращает ошибки если нет End ноды или битые ссылки
- [ ] Валидация показывается в красной полосе над холстом
- [ ] POST /scripts с dag JSON → redirect /scripts при успехе
