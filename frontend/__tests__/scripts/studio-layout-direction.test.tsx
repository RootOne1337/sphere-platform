import { render, screen } from '@testing-library/react';
import { WorkflowNode } from '@/components/sphere/dag/WorkflowNode';
import { arrangeNodes } from '@/lib/dag/studio';
import { importDag, exportDag, type DagExport } from '@/lib/dag/export';
import { layoutWorkflow } from '@/src/features/scripts/studio/layout';
import type { NodeProps } from '@xyflow/react';

const mockLayout = jest.fn();
jest.mock('elkjs/lib/elk-api', () => ({ __esModule: true, default: jest.fn().mockImplementation(() => ({ layout: mockLayout })) }));
jest.mock('@xyflow/react', () => ({
  ...jest.requireActual('@xyflow/react'),
  Handle: ({ type, id, position, title, style }: { type: string; id?: string; position: string; title: string; style: React.CSSProperties }) => (
    <span data-testid={`handle-${type}-${id ?? 'default'}`} data-position={position} title={title} style={style} />
  ),
}));

// Include both semantic branches, a failure route and a cycle. Direction is
// canvas presentation and must not rewrite any executable action or transition.
const dag: DagExport = {
  version: '1.0', entry_node: 'start', timeout_ms: 1800000, name: 'Branch canary', description: 'Preserve the wire contract',
  nodes: [
    { id: 'start', action: { type: 'start' }, on_success: 'condition', on_failure: null, retry: 0, timeout_ms: 30000 },
    { id: 'condition', action: { type: 'condition', check: 'element_exists', params: { selector: 'Settings', strategy: 'text' }, on_true: 'tap', on_false: 'wait' }, on_success: null, on_failure: 'end', retry: 1, timeout_ms: 5000 },
    { id: 'tap', action: { type: 'tap', x: 640, y: 360 }, on_success: 'end', on_failure: 'wait', retry: 0, timeout_ms: 30000 },
    { id: 'wait', action: { type: 'sleep', ms: 1000 }, on_success: 'condition', on_failure: 'end', retry: 0, timeout_ms: 30000 },
    { id: 'end', action: { type: 'end' }, on_success: null, on_failure: null, retry: 0, timeout_ms: 30000 },
  ],
};

describe('Studio layout direction preserves executable routes', () => {
  it.each(['DOWN', 'RIGHT'] as const)('changes only fallback positions for %s, retaining conditions, failure routes and polling cycles', direction => {
    const imported = importDag(dag);
    const before = JSON.stringify(imported);
    const arranged = arrangeNodes(imported.nodes, imported.edges, dag.entry_node, direction);
    const start = arranged.find(node => node.id === 'start')!.position;
    const condition = arranged.find(node => node.id === 'condition')!.position;
    const tap = arranged.find(node => node.id === 'tap')!.position;
    const wait = arranged.find(node => node.id === 'wait')!.position;
    if (direction === 'DOWN') {
      expect(start.y).toBeLessThan(condition.y); expect(condition.y).toBeLessThan(tap.y);
      expect(tap.y).toBe(wait.y); expect(tap.x).not.toBe(wait.x);
    } else {
      expect(start.x).toBeLessThan(condition.x); expect(condition.x).toBeLessThan(tap.x);
      expect(tap.x).toBe(wait.x); expect(tap.y).not.toBe(wait.y);
    }
    const painted = arranged.map(node => ({ ...node, data: { ...node.data, layoutDirection: direction, execution: 'success' } }));
    expect(exportDag(painted, imported.edges, imported.metadata)).toEqual(dag);
    expect(JSON.stringify(imported)).toBe(before);
  });

  it.each(['DOWN', 'RIGHT'] as const)('passes %s to its local ELK worker and preserves branch handles on result', async direction => {
    const terminate = jest.fn();
    const previousWorker = globalThis.Worker;
    Object.defineProperty(globalThis, 'Worker', { configurable: true, value: jest.fn(() => ({ terminate })) });
    const imported = importDag(dag);
    const originalEdges = JSON.stringify(imported.edges);
    mockLayout.mockResolvedValue({ children: imported.nodes.map((node, index) => ({ id: node.id, x: index * 30, y: index * 210 })) });
    try {
      const arranged = await layoutWorkflow(imported.nodes, imported.edges, new AbortController().signal, direction);
      const sent = mockLayout.mock.calls.at(-1)![0];
      expect(sent.layoutOptions['elk.direction']).toBe(direction);
      expect(sent.edges).toHaveLength(imported.edges.length);
      expect(exportDag(arranged, imported.edges, imported.metadata)).toEqual(dag);
      expect(JSON.stringify(imported.edges)).toBe(originalEdges);
      expect(imported.edges.filter(edge => edge.source === 'condition').map(edge => edge.sourceHandle)).toEqual(['failure', 'true_branch', 'false_branch']);
      expect(terminate).toHaveBeenCalledTimes(1);
    } finally { Object.defineProperty(globalThis, 'Worker', { configurable: true, value: previousWorker }); }
  });
});

describe('Studio renderer exposes the same handles in either direction', () => {
  function show(type: string, direction: 'DOWN' | 'RIGHT') {
    render(<WorkflowNode {...({ id: 'one', data: { action: { type }, layoutDirection: direction }, selected: false } as unknown as NodeProps)} />);
  }
  it.each(['DOWN', 'RIGHT'] as const)('keeps true/false IDs and distinct exits for %s while failure remains on the right', direction => {
    show('condition', direction);
    expect(screen.getByTestId('handle-target-default')).toHaveAttribute('data-position', direction === 'DOWN' ? 'top' : 'left');
    for (const id of ['true_branch', 'false_branch']) expect(screen.getByTestId(`handle-source-${id}`)).toHaveAttribute('data-position', direction === 'DOWN' ? 'bottom' : 'right');
    expect(screen.getByTestId('handle-source-true_branch')).toHaveAttribute('title', 'Да: on_true');
    expect(screen.getByTestId('handle-source-false_branch')).toHaveAttribute('title', 'Нет: on_false');
    expect(screen.getByTestId('handle-source-failure')).toHaveAttribute('data-position', 'right');
    expect(screen.queryByTestId('handle-source-default')).not.toBeInTheDocument();
    const one = screen.getByTestId('handle-source-true_branch'), two = screen.getByTestId('handle-source-false_branch');
    expect(direction === 'DOWN' ? one.style.left : one.style.top).not.toBe(direction === 'DOWN' ? two.style.left : two.style.top);
  });
  it.each(['DOWN', 'RIGHT'] as const)('keeps the linear success output and failure output distinct for %s', direction => {
    show('tap', direction);
    expect(screen.getByTestId('handle-source-default')).toHaveAttribute('data-position', direction === 'DOWN' ? 'bottom' : 'right');
    expect(screen.getByTestId('handle-source-default')).toHaveAttribute('title', 'Успех: on_success');
    expect(screen.getByTestId('handle-source-failure')).toHaveAttribute('data-position', 'right');
    expect(screen.queryByTestId('handle-source-true_branch')).not.toBeInTheDocument();
  });
  it('does not invent outgoing handles on an end node in the vertical layout', () => {
    show('end', 'DOWN');
    expect(screen.getByTestId('handle-target-default')).toHaveAttribute('data-position', 'top');
    expect(screen.queryByTestId('handle-source-default')).not.toBeInTheDocument();
    expect(screen.queryByTestId('handle-source-failure')).not.toBeInTheDocument();
  });
});
