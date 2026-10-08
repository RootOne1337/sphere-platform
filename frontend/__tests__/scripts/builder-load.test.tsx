import { act, createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react';
import ScriptBuilderPage from '@/app/(dashboard)/scripts/builder/page';
import { api } from '@/lib/api';
import { TextEncoder } from 'node:util';
import { deserialize, serialize } from 'node:v8';
import type { ReactFlowProps } from '@xyflow/react';
import { ACTION_DRAG_TYPE } from '@/lib/dag/canvasPlacement';
import { navigateFromWorkspace, workspaceNavigationAllowed } from '@/src/features/navigation/workspaceNavigationGuard';
Object.assign(globalThis, { TextEncoder });
Object.defineProperty(globalThis, 'structuredClone', { configurable: true, value: (value: unknown) => deserialize(serialize(value)) });

let mockEditId: string | null = 'script-a';
const mockPush = jest.fn();
const mockInvalidate = jest.fn().mockResolvedValue(undefined);
jest.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: mockInvalidate }) }));
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(mockEditId ? { id: mockEditId } : {}),
}));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), put: jest.fn(), post: jest.fn() } }));
let mockCanWrite = true;
let mockCanRead = true;
let mockSessionVersion = 0;
jest.mock('@/src/features/access/Capabilities', () => ({ useCapabilities: () => ({ pending: false, can: (permission: string) => permission === 'script:read' ? mockCanRead : mockCanWrite }) }));
jest.mock('@/lib/store', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: 'operator', org_id: 'org-a' }, sessionVersion: mockSessionVersion }) }));
const mockRunModal = jest.fn();
jest.mock('@/components/sphere/RunScriptModal', () => ({ RunScriptModal: (props: unknown) => { mockRunModal(props); return null; } }));
const mockWorkbenchGuard = jest.fn((_silent?: boolean, _confirmDiscard?: boolean) => true);
jest.mock('@/src/features/scripts/studio/DeviceWorkbench', () => ({ DeviceWorkbench: ({ registerCloseGuard, onExecution }: { registerCloseGuard: (guard: ((silent?: boolean) => boolean) | null) => void; onExecution: (last: string | null, logs: { node_id: string; success: boolean }[]) => void }) => {
  const React = jest.requireActual('react');
  React.useEffect(() => { registerCloseGuard(mockWorkbenchGuard); return () => registerCloseGuard(null); }, [registerCloseGuard]);
  return <div>Owned workbench<button onClick={() => onExecution('script-a-start', [{ node_id: 'script-a-start', success: true }])}>Report workbench execution</button></div>;
} }));
jest.mock('@/lib/dag/nodeTypes', () => ({ nodeTypes: {} }));
jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => null }));
jest.mock('@xyflow/react/dist/style.css', () => ({}));
const mockFitView = jest.fn().mockResolvedValue(true);
const mockScreenToFlowPosition = jest.fn(({ x, y }: { x: number; y: number }) => ({ x: (x - 100) / 2, y: (y - 50) / 2 }));
let mockGraphProps: ReactFlowProps = {};
jest.mock('@xyflow/react', () => {
  const React = jest.requireActual('react');
  const { applyNodeChanges, applyEdgeChanges, addEdge } = jest.requireActual('@xyflow/react');
  return {
    useNodesState: (initial: unknown) => {
      const [nodes, setNodes] = React.useState(initial);
      const onChange = React.useCallback((changes: unknown) => setNodes((current: unknown) => applyNodeChanges(changes, current)), []);
      return [nodes, setNodes, onChange];
    },
    useEdgesState: (initial: unknown) => {
      const [edges, setEdges] = React.useState(initial);
      const onChange = React.useCallback((changes: unknown) => setEdges((current: unknown) => applyEdgeChanges(changes, current)), []);
      return [edges, setEdges, onChange];
    },
    addEdge,
    ReactFlow: (props: ReactFlowProps) => {
      mockGraphProps = props;
      React.useEffect(() => { props.onInit?.({ fitView: mockFitView, screenToFlowPosition: mockScreenToFlowPosition } as never); }, []);
      return <div data-testid="graph">{props.nodes?.map((node) => <button key={node.id} onClick={event => props.onNodeClick?.(event, node)}>{node.id}</button>)}{props.edges?.map(edge => <button key={edge.id} onClick={event => props.onEdgeClick?.(event, edge)}>Связь {edge.id}</button>)}</div>;
    },
    Background: () => null, Controls: () => null, MiniMap: () => null,
  };
});

function payload(id = 'script-a', name = 'Original graph') {
  return { data: { id, name, current_version_id: `${id}-version`, current_version: { dag: {
    version: '1.0', timeout_ms: 1800000, entry_node: `${id}-start`, nodes: [
      { id: `${id}-start`, action: { type: 'start' }, on_success: `${id}-end`, on_failure: null, retry: 0, timeout_ms: 30000 },
      { id: `${id}-end`, action: { type: 'end' }, on_success: null, on_failure: null, retry: 0, timeout_ms: 30000 },
    ],
  } } } };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => { jest.clearAllMocks(); mockGraphProps = {}; mockWorkbenchGuard.mockReturnValue(true); mockEditId = 'script-a'; mockCanWrite = true; mockCanRead = true; mockSessionVersion = 0; localStorage.clear(); });
afterEach(() => jest.restoreAllMocks());

it('keeps an unpublished document and laboratory mounted but hidden while permissions are unavailable', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  const view = render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.change(screen.getByLabelText('Название сценария'), { target: { value: 'Unsaved outage draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Устройство · запись · проверка' }));
  fireEvent.click(screen.getByRole('button', { name: 'Report workbench execution' }));
  mockWorkbenchGuard.mockReturnValue(false); mockCanRead = false; mockCanWrite = false;
  view.rerender(<ScriptBuilderPage />);
  expect(screen.getByText('Owned workbench')).not.toBeVisible();
  expect(screen.getByLabelText('Название сценария')).toHaveValue('Unsaved outage draft');
  expect(workspaceNavigationAllowed()).toBe(false);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled();
  mockCanRead = true; mockCanWrite = true;
  view.rerender(<ScriptBuilderPage />);
  expect(screen.getByText('Owned workbench')).toBeVisible();
  expect(screen.getByLabelText('Название сценария')).toHaveValue('Unsaved outage draft');
  expect(api.get).toHaveBeenCalledTimes(1);
});

it('suspends an already opened portalled launch modal instead of unmounting its pending receipt', async () => {
  const response = payload();
  Object.assign(response.data.current_version, { id: 'script-a-version', version: 1, dag_hash: 'a'.repeat(64) });
  jest.mocked(api.get).mockResolvedValue(response as never);
  const view = render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Запустить версию' }));
  expect(mockRunModal).toHaveBeenLastCalledWith(expect.objectContaining({ open: true, suspended: false }));
  mockCanRead = false; mockCanWrite = false;
  view.rerender(<ScriptBuilderPage />);
  expect(mockRunModal).toHaveBeenLastCalledWith(expect.objectContaining({ open: true, suspended: true }));
  mockCanRead = true; mockCanWrite = true;
  view.rerender(<ScriptBuilderPage />);
  expect(mockRunModal).toHaveBeenLastCalledWith(expect.objectContaining({ open: true, suspended: false }));
  expect(api.post).not.toHaveBeenCalled();
});

it('protects dirty graph/source through an outside navigation link and honors explicit cancellation', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.change(screen.getByLabelText('Название сценария'), { target: { value: 'Unpublished edit' } });
  const anchor = document.createElement('a'); anchor.href = '/devices';
  const follow = jest.fn((event: MouseEvent) => event.preventDefault()); anchor.addEventListener('click', follow); document.body.append(anchor);
  try {
    fireEvent.click(anchor);
    expect(screen.getByRole('dialog', { name: 'Сохранить работу перед выходом?' })).toBeInTheDocument(); expect(follow).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Остаться в редакторе' }));
    expect(screen.getByLabelText('Название сценария')).toHaveValue('Unpublished edit');
    fireEvent.click(anchor); fireEvent.click(screen.getByRole('button', { name: 'Выйти без сохранения' }));
    await waitFor(() => expect(follow).toHaveBeenCalledTimes(1));
    expect(api.put).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
  } finally { anchor.remove(); }
});

it('checks the workbench before allowing a global programmatic transition', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  const view = render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Устройство · запись · проверка' }));
  mockWorkbenchGuard.mockReturnValue(false);
  expect(workspaceNavigationAllowed()).toBe(false);
  expect(mockWorkbenchGuard).toHaveBeenLastCalledWith(false, false);
  expect(screen.getByText('Owned workbench')).toBeInTheDocument(); expect(mockPush).not.toHaveBeenCalled();
  mockWorkbenchGuard.mockReturnValue(true); expect(workspaceNavigationAllowed()).toBe(true);
  view.unmount(); expect(workspaceNavigationAllowed()).toBe(true);
});

it('owns one navigation intent until cancellation and preserves the edited document', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.change(screen.getByLabelText('Название сценария'), { target: { value: 'Keep this draft' } });
  const first = jest.fn(); const second = jest.fn();
  act(() => { navigateFromWorkspace(first); navigateFromWorkspace(second); });
  expect(screen.getAllByRole('dialog')).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Остаться в редакторе' }));
  await act(async () => {});
  expect(first).not.toHaveBeenCalled(); expect(second).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Название сценария')).toHaveValue('Keep this draft');
  expect(api.put).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
});

it('cancels a pending navigation when the owning auth session is replaced', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  const view = render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.change(screen.getByLabelText('Название сценария'), { target: { value: 'Private old draft' } });
  const follow = jest.fn(); act(() => navigateFromWorkspace(follow));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  mockSessionVersion += 1; view.rerender(<ScriptBuilderPage />);
  await screen.findByDisplayValue('Original graph');
  await act(async () => {});
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); expect(follow).not.toHaveBeenCalled();
  expect(api.put).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
});

it('rechecks a live workbench command before approving an already open leave dialog', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Устройство · запись · проверка' }));
  // A retained recording can be discarded after approval, unlike a pending command.
  mockWorkbenchGuard.mockImplementation((silent) => !silent);
  const follow = jest.fn(); act(() => navigateFromWorkspace(follow));
  expect(screen.getByRole('dialog')).toHaveTextContent('Лаборатория устройства');
  mockWorkbenchGuard.mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', { name: 'Выйти без сохранения' }));
  await act(async () => {});
  expect(follow).not.toHaveBeenCalled(); expect(screen.getByText('Owned workbench')).toBeInTheDocument();
  expect(mockWorkbenchGuard).toHaveBeenLastCalledWith(false, false);
  expect(api.put).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
});

it('blocks navigation and page unload while a save is pending, then keeps the successful save redirect', async () => {
  const response = deferred<never>();
  jest.mocked(api.get).mockResolvedValue(payload() as never); jest.mocked(api.put).mockReturnValue(response.promise);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
  act(() => { expect(workspaceNavigationAllowed()).toBe(false); });
  expect(screen.getByRole('alert')).toHaveTextContent('Дождитесь результата'); expect(mockPush).not.toHaveBeenCalled();
  const unload = new Event('beforeunload', { cancelable: true }); fireEvent(window, unload); expect(unload.defaultPrevented).toBe(true);
  await act(async () => response.resolve({ data: {} } as never));
  await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/scripts'));
  expect(workspaceNavigationAllowed()).toBe(true);
});

function actionDrop(type: string, x = 800, y = 400, mime = ACTION_DRAG_TYPE) {
  const pane = screen.getByLabelText('Поле графа');
  const dataTransfer = { types: [mime], getData: jest.fn(() => type), setData: jest.fn(), effectAllowed: '', dropEffect: '' };
  fireEvent.dragOver(pane, { dataTransfer });
  const event = createEvent.drop(pane, { dataTransfer });
  Object.defineProperties(event, { clientX: { value: x }, clientY: { value: y } });
  fireEvent(pane, event);
  return dataTransfer;
}

it('creates a separate node by default, keeps old routes and lets the operator connect it before publication', async () => {
  mockEditId = null;
  jest.mocked(api.post).mockResolvedValue({ data: { id: 'created' } } as never);
  render(<ScriptBuilderPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Добавить узел: Ожидание' }));
  const added = mockGraphProps.nodes!.find(node => node.data.action && (node.data.action as { type: string }).type === 'sleep')!;
  expect(mockGraphProps.edges).toHaveLength(1);
  expect(mockGraphProps.edges![0]).toMatchObject({ source: 'start-1', target: 'end-1' });
  expect(screen.getByLabelText('Граф не готов к публикации')).toHaveTextContent(added.id);
  fireEvent.click(screen.getByRole('button', { name: 'Создать сценарий' }));
  expect(screen.getByRole('alert')).toHaveTextContent('недостижим'); expect(api.post).not.toHaveBeenCalled();
  const old = mockGraphProps.edges![0];
  act(() => mockGraphProps.onReconnect?.(old, { source: 'start-1', target: added.id, sourceHandle: null, targetHandle: null }));
  act(() => mockGraphProps.onConnect?.({ source: added.id, target: 'end-1', sourceHandle: null, targetHandle: null }));
  expect(screen.queryByLabelText('Граф не готов к публикации')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Создать сценарий' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  const request = jest.mocked(api.post).mock.calls[0][1] as { dag: { nodes: { id: string; on_success: string }[] } };
  expect(request.dag.nodes.find(node => node.id === 'start-1')!.on_success).toBe(added.id);
});

it('inserts into a chain without obscuring the existing completion node and preserves the executable route', () => {
  mockEditId = null;
  render(<ScriptBuilderPage />);
  const before = mockGraphProps.nodes!.map(node => ({ id: node.id, position: { ...node.position } }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Способ добавления действия' }), { target: { value: 'insert' } });
  fireEvent.click(screen.getByRole('button', { name: 'Добавить узел: Ожидание' }));
  const inserted = mockGraphProps.nodes!.find(node => !before.some(old => old.id === node.id))!;
  for (const old of before) {
    expect(mockGraphProps.nodes!.find(node => node.id === old.id)!.position).toEqual(old.position);
    const p = inserted.position; const q = old.position;
    expect(p.x + 256 <= q.x || q.x + 256 <= p.x || p.y + 132 <= q.y || q.y + 132 <= p.y).toBe(true);
  }
  fireEvent.click(screen.getByRole('button', { name: 'JSON' }));
  const dag = JSON.parse((screen.getByLabelText(/Исходник DAG 1.0/) as HTMLTextAreaElement).value);
  expect(dag.nodes.find((node: { id: string }) => node.id === 'start-1').on_success).toBe(inserted.id);
  expect(dag.nodes.find((node: { id: string }) => node.id === inserted.id).on_success).toBe('end-1');
  expect(api.post).not.toHaveBeenCalled();
});

it('drops at the transformed pointer, preserves old positions and viewport, and ignores the insertion preference for dragging', () => {
  mockEditId = null;
  render(<ScriptBuilderPage />);
  fireEvent.change(screen.getByRole('combobox', { name: 'Способ добавления действия' }), { target: { value: 'insert' } });
  act(() => mockGraphProps.onNodesChange?.([{ id: 'start-1', type: 'position', position: { x: 345, y: 678 } }]));
  const before = mockGraphProps.nodes!.map(node => ({ id: node.id, position: node.position }));
  const palette = screen.getByRole('button', { name: 'Добавить узел: Нажатие' });
  const dataTransfer = { setData: jest.fn(), effectAllowed: '' };
  fireEvent.dragStart(palette, { dataTransfer });
  expect(dataTransfer.setData).toHaveBeenCalledWith(ACTION_DRAG_TYPE, 'tap');
  expect(dataTransfer.effectAllowed).toBe('copy');
  actionDrop('tap');
  expect(mockScreenToFlowPosition).toHaveBeenLastCalledWith({ x: 800, y: 400 });
  const node = mockGraphProps.nodes!.find(node => !before.some(old => old.id === node.id))!;
  expect(node.position).toEqual({ x: 222, y: 151 });
  expect(mockGraphProps.nodes!.filter(item => item.id !== node.id).map(item => ({ id: item.id, position: item.position }))).toEqual(before);
  expect(mockGraphProps.edges).toHaveLength(1);
  expect(mockFitView).not.toHaveBeenCalled();
  expect(screen.queryByText('Отпустите, чтобы добавить отдельный узел')).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled();
});

it('lets an unfinished condition be edited and survive source/graph switches without inventing branch targets', () => {
  mockEditId = null;
  render(<ScriptBuilderPage />); actionDrop('condition');
  const added = mockGraphProps.nodes!.find(node => (node.data.action as { type: string }).type === 'condition')!;
  expect(screen.getByLabelText('Граф не готов к публикации')).toHaveTextContent('требуется on_true');
  fireEvent.click(screen.getByRole('button', { name: 'JSON шага' }));
  const source = screen.getByLabelText('Шаг JSON: action, переходы, retry, timeout_ms') as HTMLTextAreaElement;
  const value = JSON.parse(source.value); value.action.params = { level: 30 };
  fireEvent.change(source, { target: { value: JSON.stringify(value) } });
  fireEvent.click(screen.getByRole('button', { name: 'Применить параметры' }));
  expect(mockGraphProps.nodes!.find(node => node.id === added.id)!.position).toEqual(added.position);
  fireEvent.click(screen.getByRole('button', { name: 'JSON' }));
  const graph = JSON.parse((screen.getByLabelText(/Исходник DAG/) as HTMLTextAreaElement).value);
  expect(graph.nodes.find((node: { id: string }) => node.id === added.id).action).toEqual({ type: 'condition', check: 'battery_above', params: { level: 30 } });
  fireEvent.click(screen.getByRole('button', { name: 'Граф' }));
  expect(mockGraphProps.nodes).toHaveLength(3);
  expect(mockGraphProps.edges).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на сервере' }));
  expect(screen.getByRole('alert')).toHaveTextContent('требуется on_true');
  expect(api.post).not.toHaveBeenCalled();
});

it('does not accept unknown/foreign drag data or a stale drop after permissions change', () => {
  mockEditId = null;
  const view = render(<ScriptBuilderPage />);
  actionDrop('loop'); expect(screen.getByRole('alert')).toHaveTextContent('Неизвестное действие');
  actionDrop('tap', 800, 400, 'text/plain');
  expect(mockGraphProps.nodes).toHaveLength(2);
  mockCanWrite = false; view.rerender(<ScriptBuilderPage />);
  expect(screen.getByRole('button', { name: 'Добавить узел: Нажатие' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Добавить узел: Нажатие' })).toHaveAttribute('draggable', 'false');
  actionDrop('tap'); expect(mockGraphProps.nodes).toHaveLength(2);
  expect(api.post).not.toHaveBeenCalled();
});

it('protects the entry, supports deleting other steps and rebuilding the one-step draft with undo', async () => {
  mockEditId = null;
  render(<ScriptBuilderPage />);
  fireEvent.click(screen.getByRole('button', { name: 'start-1' }));
  expect(screen.getByRole('button', { name: 'Удалить шаг' })).toBeDisabled();
  let allowed: unknown;
  await act(async () => { allowed = await mockGraphProps.onBeforeDelete?.({ nodes: [mockGraphProps.nodes![0]], edges: [] }); });
  expect(allowed).toBe(false);
  expect(screen.getByRole('alert')).toHaveTextContent('Начальный шаг нельзя удалить');
  fireEvent.click(screen.getByRole('button', { name: 'end-1' }));
  fireEvent.click(screen.getByRole('button', { name: 'Удалить шаг' }));
  expect(mockGraphProps.nodes).toHaveLength(1); expect(mockGraphProps.edges).toHaveLength(0);
  actionDrop('end'); expect(mockGraphProps.nodes).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: 'Отменить изменение' }));
  expect(screen.getByTestId('graph')).toBeInTheDocument();
  expect(mockGraphProps.nodes).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Отменить изменение' }));
  expect(screen.getByTestId('graph')).toBeInTheDocument();
  expect(mockGraphProps.nodes).toHaveLength(2); expect(mockGraphProps.edges).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Повторить изменение' }));
  expect(screen.getByTestId('graph')).toBeInTheDocument();
  expect(mockGraphProps.nodes).toHaveLength(1);
  expect(api.post).not.toHaveBeenCalled();
});

it('can select a new entry before deleting the original start without changing node coordinates', () => {
  mockEditId = null; render(<ScriptBuilderPage />);
  actionDrop('tap');
  const added = mockGraphProps.nodes!.find(node => (node.data.action as { type: string }).type === 'tap')!;
  fireEvent.click(screen.getByRole('button', { name: 'Сценарий' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Начальный шаг сценария' }), { target: { value: added.id } });
  expect(mockGraphProps.nodes!.find(node => node.id === added.id)!.position).toEqual(added.position);
  fireEvent.click(screen.getByRole('button', { name: 'start-1' }));
  expect(screen.getByRole('button', { name: 'Удалить шаг' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Удалить шаг' }));
  expect(mockGraphProps.nodes?.some(node => node.id === 'start-1')).toBe(false);
  act(() => mockGraphProps.onConnect?.({ source: added.id, target: 'end-1', sourceHandle: null, targetHandle: null }));
  expect(screen.queryByLabelText('Граф не готов к публикации')).not.toBeInTheDocument();
});

it('keeps unfinished-node parameters protected from a drop and supports editing after removing a route', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Связь e-script-a-start-next-script-a-end' }));
  fireEvent.click(screen.getByRole('button', { name: 'Разорвать связь' }));
  fireEvent.click(screen.getByRole('button', { name: 'Добавить узел: Ожидание' }));
  expect(mockGraphProps.nodes).toHaveLength(3);
  expect(mockGraphProps.edges).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: 'JSON шага' }));
  const field = screen.getByLabelText('Шаг JSON: action, переходы, retry, timeout_ms');
  fireEvent.change(field, { target: { value: '{not applied' } });
  actionDrop('tap'); expect(mockGraphProps.nodes).toHaveLength(3);
  expect(field).toHaveValue('{not applied');
  expect(screen.getByRole('button', { name: 'Добавить узел: Нажатие' })).toHaveAttribute('draggable', 'false');
  fireEvent.click(screen.getByRole('button', { name: 'Отменить параметры' }));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

function animationFrames() {
  let nextId = 0;
  const frames = new Map<number, FrameRequestCallback>();
  jest.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { frames.set(++nextId, callback); return nextId; });
  jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(id => { frames.delete(id); });
  return () => act(() => {
    const callbacks = [...frames.values()]; frames.clear();
    callbacks.forEach(callback => callback(performance.now()));
  });
}

function canvasSizes() {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'ResizeObserver');
  const observers: { callback: ResizeObserverCallback; element: Element | null; disconnected: boolean }[] = [];
  class Observer {
    state: typeof observers[number];
    constructor(callback: ResizeObserverCallback) { this.state = { callback, element: null, disconnected: false }; observers.push(this.state); }
    observe(element: Element) { this.state.element = element; }
    unobserve() {}
    disconnect() { this.state.disconnected = true; }
  }
  Object.defineProperty(globalThis, 'ResizeObserver', { configurable: true, value: Observer });
  return {
    resize: (width: number, height: number, stale = false) => act(() => {
      for (const observer of observers) if (observer.element && (stale || !observer.disconnected)) {
        observer.callback([{ target: observer.element, contentRect: { width, height } } as ResizeObserverEntry], {} as ResizeObserver);
      }
    }),
    disconnected: () => observers.every(observer => observer.disconnected),
    restore: () => { if (previous) Object.defineProperty(globalThis, 'ResizeObserver', previous); else Reflect.deleteProperty(globalThis, 'ResizeObserver'); },
  };
}

it('adapts an overview to pane resizing without stealing a manually chosen viewport or changing the DAG', () => {
  const sizes = canvasSizes(); const frame = animationFrames();
  try {
    mockEditId = null;
    render(<ScriptBuilderPage />);
    const before = mockGraphProps.nodes!.map(node => ({ id: node.id, position: { ...node.position } }));
    const routes = structuredClone(mockGraphProps.edges);
    sizes.resize(1000, 700); frame(); frame();
    expect(mockFitView).not.toHaveBeenCalled();
    sizes.resize(500, 600); sizes.resize(510, 600); frame();
    expect(mockFitView).not.toHaveBeenCalled();
    frame(); expect(mockFitView).toHaveBeenCalledTimes(1);
    expect(mockFitView).toHaveBeenLastCalledWith(expect.objectContaining({ minZoom: 0.15, maxZoom: 1 }));
    act(() => mockGraphProps.onMoveStart?.(null, { x: 10, y: 20, zoom: 1 }));
    sizes.resize(600, 600); frame(); frame();
    expect(mockFitView).toHaveBeenCalledTimes(2); // Programmatic fit doesn't cancel overview following.
    sizes.resize(620, 600); frame();
    act(() => mockGraphProps.onMoveStart?.(new MouseEvent('mousedown'), { x: 30, y: 40, zoom: 1.5 }));
    frame(); sizes.resize(630, 600); frame(); frame();
    expect(mockFitView).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: 'Весь граф' }));
    sizes.resize(640, 600); frame(); frame();
    expect(mockFitView).toHaveBeenCalledTimes(4);
    fireEvent.change(screen.getByLabelText('Название сценария'), { target: { value: 'Readable overview' } });
    sizes.resize(640.2, 600.1); frame(); frame();
    expect(mockFitView).toHaveBeenCalledTimes(4);
    expect(mockGraphProps.nodes!.map(node => ({ id: node.id, position: node.position }))).toEqual(before);
    expect(mockGraphProps.edges).toEqual(routes);
    expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled();
  } finally { sizes.restore(); }
});

it('ignores hidden panes and cancels observer work on source mode, unmount and stale callbacks', () => {
  const sizes = canvasSizes(); const frame = animationFrames();
  try {
    mockEditId = null;
    const view = render(<ScriptBuilderPage />);
    sizes.resize(1000, 700); sizes.resize(0, 0); frame(); frame();
    expect(mockFitView).not.toHaveBeenCalled();
    sizes.resize(400, 500); frame(); frame();
    expect(mockFitView).toHaveBeenCalledTimes(1);
    sizes.resize(450, 500); frame();
    fireEvent.click(screen.getByRole('button', { name: 'JSON' }));
    sizes.resize(460, 500, true); frame(); frame();
    expect(sizes.disconnected()).toBe(true);
    expect(mockFitView).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Граф' }));
    sizes.resize(600, 500); sizes.resize(650, 500); frame();
    view.unmount(); sizes.resize(700, 500, true); frame(); frame();
    expect(sizes.disconnected()).toBe(true);
    expect(mockFitView).toHaveBeenCalledTimes(1);
  } finally { sizes.restore(); }
});

it('keeps invalid imported parameters editable but blocks publication and validation before HTTP', async () => {
  const response = payload();
  response.data.current_version.dag.nodes[0].action = { type: 'set_variable', key: 'v', value: {} } as never;
  jest.mocked(api.get).mockResolvedValue(response as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'script-a-start' }));
  expect(screen.getByRole('region', { name: 'Контракт действия' })).toHaveTextContent('объект и массив не поддерживаются APK');
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('nodes.0.action.value');
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на сервере' }));
  expect(api.put).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'JSON шага' }));
  const source = screen.getByLabelText('Шаг JSON: action, переходы, retry, timeout_ms');
  fireEvent.change(source, { target: { value: JSON.stringify({ ...response.data.current_version.dag.nodes[0], action: { type: 'set_variable', key: 'v', value: 3 } }) } });
  fireEvent.click(screen.getByRole('button', { name: 'Применить параметры' }));
  jest.mocked(api.put).mockResolvedValue({ data: {} } as never);
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
});

it.each([undefined, '1.0', '2.0'])('labels server parameter coverage honestly for receipt %s', async contractVersion => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  const receipt = { schema_version: 1, dag_hash: 'a'.repeat(64), node_count: 2, scope: 'structure-routes-lua-safety', device_execution_verified: false,
    ...(contractVersion ? { action_contract_version: contractVersion, action_parameters_verified: true } : {}) };
  jest.mocked(api.post).mockResolvedValue({ data: receipt } as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на сервере' }));
  if (contractVersion === '2.0') {
    expect(await screen.findByRole('alert')).toHaveTextContent('контракта параметров не подтверждена');
    expect(screen.queryByText(/Параметры действий проверены сервером/)).not.toBeInTheDocument();
  } else if (contractVersion) expect(await screen.findByText(/Параметры действий проверены сервером/)).toBeInTheDocument();
  else expect(await screen.findByText(/этот API не подтвердил проверку параметров/)).toBeInTheDocument();
  expect(api.put).not.toHaveBeenCalled();
});

it('adds an Android navigation preset to the graph without issuing live input', async () => {
  mockEditId = null;
  Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: () => '00000000-0000-4000-8000-000000000012' });
  render(<ScriptBuilderPage />);
  const presets = screen.getByLabelText('Готовые клавиши Android');
  expect(presets).not.toHaveAttribute('open');
  fireEvent.click(screen.getByText('Клавиши Android · 6'));
  expect(presets).toHaveAttribute('open');
  fireEvent.change(screen.getByRole('combobox', { name: 'Способ добавления действия' }), { target: { value: 'insert' } });
  fireEvent.click(screen.getByRole('button', { name: 'Добавить действие Домой' }));
  expect(mockGraphProps.nodes).toHaveLength(3);
  fireEvent.click(screen.getByRole('button', { name: 'JSON' }));
  const graph = JSON.parse((screen.getByLabelText(/Исходник DAG/) as HTMLTextAreaElement).value);
  const key = graph.nodes.find((node: { action: { type: string } }) => node.action.type === 'key_event');
  expect(key.action).toEqual({ type: 'key_event', keycode: 3 });
  expect(graph.nodes.find((node: { id: string }) => node.id === graph.entry_node).on_success).toBe(key.id);
  expect(key.on_success).toBe('end-1');
  expect(api.post).not.toHaveBeenCalled(); expect(api.put).not.toHaveBeenCalled();
});

it('exposes a connection inspector and removes the canonical transition without deleting either step', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Связь e-script-a-start-next-script-a-end' }));
  expect(screen.getByRole('region', { name: 'Редактор связи' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Разорвать связь' }));
  expect(mockGraphProps.nodes).toHaveLength(2); expect(mockGraphProps.edges).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('недостижим');
  expect(api.put).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'JSON' }));
  const removed = JSON.parse((screen.getByLabelText(/Исходник DAG/) as HTMLTextAreaElement).value);
  expect(removed.nodes[0].on_success).toBeNull(); expect(removed.nodes).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: 'Отменить изменение' }));
  const restored = JSON.parse((screen.getByLabelText(/Исходник DAG/) as HTMLTextAreaElement).value);
  expect(restored.nodes[0].on_success).toBe('script-a-end');
});

it('serializes reconnection from the inspector and the canvas through the same route contract', async () => {
  const response = payload();
  response.data.current_version.dag.nodes.splice(1, 0, { id: 'pause', action: { type: 'sleep', ms: 10 } as never, on_success: 'script-a-end', on_failure: null, retry: 0, timeout_ms: 30000 });
  response.data.current_version.dag.nodes[0].on_success = 'pause';
  jest.mocked(api.get).mockResolvedValue(response as never);
  jest.mocked(api.put).mockResolvedValue({ data: {} } as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Связь e-script-a-start-next-pause' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Выход связи' }), { target: { value: 'failure' } });
  expect(mockGraphProps.edges?.find(edge => edge.source === 'script-a-start')).toMatchObject({ sourceHandle: 'failure', target: 'pause' });
  const changed = mockGraphProps.edges!.find(edge => edge.source === 'script-a-start')!;
  act(() => mockGraphProps.onReconnect?.(changed, { source: 'script-a-start', sourceHandle: null, target: 'pause', targetHandle: null }));
  expect(mockGraphProps.edges?.find(edge => edge.id === changed.id)?.sourceHandle).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  await waitFor(() => expect(api.put).toHaveBeenCalled());
  expect(jest.mocked(api.put).mock.calls[0][1]).toMatchObject({ dag: response.data.current_version.dag });
});

it('blocks inspector and canvas connection edits while parameters are unapplied or permissions are read only', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  const view = render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  mockCanWrite = false; view.rerender(<ScriptBuilderPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Связь e-script-a-start-next-script-a-end' }));
  expect(screen.getByRole('button', { name: 'Разорвать связь' })).toBeDisabled();
  expect(screen.getByRole('combobox', { name: 'Выход связи' })).toBeDisabled();
  expect(mockGraphProps.edgesReconnectable).toBe(false);
  const existing = mockGraphProps.edges![0];
  act(() => mockGraphProps.onReconnect?.(existing, { source: existing.source, target: existing.target, sourceHandle: 'failure', targetHandle: null }));
  expect(mockGraphProps.edges![0].sourceHandle).toBeNull();
  mockCanWrite = true; view.rerender(<ScriptBuilderPage />);
  fireEvent.click(screen.getByRole('button', { name: 'script-a-start' }));
  fireEvent.click(screen.getByRole('button', { name: 'JSON шага' }));
  fireEvent.change(screen.getByLabelText('Шаг JSON: action, переходы, retry, timeout_ms'), { target: { value: '{pending' } });
  expect(mockGraphProps.edgesReconnectable).toBe(false);
  act(() => mockGraphProps.onEdgeClick?.({} as never, existing));
  expect(screen.getByRole('alert')).toHaveTextContent('параметры текущего шага');
  act(() => mockGraphProps.onReconnect?.(existing, { source: existing.source, target: existing.target, sourceHandle: 'failure', targetHandle: null }));
  expect(mockGraphProps.edges![0].sourceHandle).toBeNull();
});

it('lets an operator edit connections while keeping the device workbench mounted', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Устройство · запись · проверка' }));
  fireEvent.click(screen.getByRole('button', { name: 'Связь e-script-a-start-next-script-a-end' }));
  expect(screen.getByText('Owned workbench')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Разорвать связь' }));
  expect(screen.getByText('Owned workbench')).toBeInTheDocument();
  expect(mockGraphProps.edges).toHaveLength(0);
});

it('keeps a failed existing-script read out of the editor and only saves its original graph after explicit retry', async () => {
  jest.mocked(api.get).mockRejectedValueOnce(new Error('network timeout')).mockResolvedValueOnce(payload() as never);
  jest.mocked(api.put).mockResolvedValue({ data: {} } as never);
  render(<ScriptBuilderPage />);
  expect(await screen.findByRole('alert')).toHaveTextContent('network timeout');
  expect(screen.queryByTestId('graph')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Сохранить версию' })).not.toBeInTheDocument();
  expect(api.put).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }));
  expect(await screen.findByText('script-a-start')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/scripts/script-a', {
    name: 'Original graph', dag: payload().data.current_version.dag, expected_current_version_id: 'script-a-version',
  }, expect.objectContaining({ signal: expect.any(AbortSignal) })));
  expect(api.post).not.toHaveBeenCalled();
  expect(mockInvalidate).toHaveBeenCalledWith({ queryKey: ['scripts'] });
});

it.each([
  ['missing DAG', { data: { id: 'script-a', name: 'No graph' } }],
  ['wrong resource', payload('script-b')],
  ['invalid entry', { data: { id: 'script-a', current_version: { dag: { entry_node: 'missing', nodes: {} } } } }],
  ['missing version', { data: { ...payload().data, current_version_id: null } }],
  ['archived script', { data: { ...payload().data, is_archived: true } }],
])('does not turn %s into the initial editable template', async (_, response) => {
  jest.mocked(api.get).mockResolvedValue(response as never);
  render(<ScriptBuilderPage />);
  expect(await screen.findByText('Сценарий не загружен')).toBeInTheDocument();
  expect(screen.queryByTestId('graph')).not.toBeInTheDocument();
  expect(api.put).not.toHaveBeenCalled();
});

it('aborts and ignores the previous resource read when the selected script changes', async () => {
  const old = deferred<ReturnType<typeof payload>>();
  jest.mocked(api.get).mockReturnValueOnce(old.promise as never).mockResolvedValueOnce(payload('script-b', 'B graph') as never);
  const view = render(<ScriptBuilderPage />);
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
  const signal = jest.mocked(api.get).mock.calls[0][1]?.signal;
  mockEditId = 'script-b';
  view.rerender(<ScriptBuilderPage />);
  expect(await screen.findByText('script-b-start')).toBeInTheDocument();
  expect(signal?.aborted).toBe(true);
  await act(async () => old.resolve(payload()));
  expect(screen.queryByText('script-a-start')).not.toBeInTheDocument();
  expect(screen.getByDisplayValue('B graph')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/scripts/script-b', expect.objectContaining({ name: 'B graph' }), expect.objectContaining({ signal: expect.any(AbortSignal) })));
});

it('a failed read of the new target cannot save the old graph under the new ID', async () => {
  jest.mocked(api.get).mockResolvedValueOnce(payload() as never).mockRejectedValueOnce(new Error('B denied'));
  const view = render(<ScriptBuilderPage />);
  await screen.findByText('script-a-start');
  mockEditId = 'script-b';
  view.rerender(<ScriptBuilderPage />);
  expect(await screen.findByRole('alert')).toHaveTextContent('B denied');
  expect(screen.queryByTestId('graph')).not.toBeInTheDocument();
  expect(api.put).not.toHaveBeenCalled();
});

it('keeps new-script creation independent of the existing-resource loader', async () => {
  mockEditId = null;
  jest.mocked(api.post).mockResolvedValue({ data: {} } as never);
  render(<ScriptBuilderPage />);
  expect(screen.getByText('start-1')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Создать сценарий' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/scripts', expect.objectContaining({ dag: expect.any(Object) }), expect.objectContaining({ signal: expect.any(AbortSignal) })));
  expect(api.get).not.toHaveBeenCalled();
  expect(api.put).not.toHaveBeenCalled();
  expect(mockInvalidate).toHaveBeenCalledWith({ queryKey: ['scripts'] });
});

it('does not navigate the next editor when the previous save completes', async () => {
  const save = deferred<unknown>();
  jest.mocked(api.get).mockResolvedValueOnce(payload() as never).mockResolvedValueOnce(payload('script-b') as never);
  jest.mocked(api.put).mockReturnValue(save.promise as never);
  const view = render(<ScriptBuilderPage />);
  await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  mockEditId = 'script-b';
  view.rerender(<ScriptBuilderPage />);
  await screen.findByText('script-b-start');
  await act(async () => save.resolve({ data: {} }));
  expect(mockPush).not.toHaveBeenCalled();
});

it('surfaces version conflicts without retrying or navigating away from the graph', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  jest.mocked(api.put).mockRejectedValue({ isAxiosError: true, response: { status: 409 } });
  render(<ScriptBuilderPage />);
  await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  expect(await screen.findByText(/Сохранение отклонено/)).toBeInTheDocument();
  expect(api.put).toHaveBeenCalledTimes(1);
  expect(mockInvalidate).not.toHaveBeenCalled();
  expect(screen.getByTestId('graph')).toBeInTheDocument();
  expect(mockPush).not.toHaveBeenCalled();
});

it('retains invalid JSON and blocks save without falling back to the previous graph', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'JSON' }));
  fireEvent.change(screen.getByLabelText(/Исходник DAG/), { target: { value: '{ broken' } });
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Некорректный JSON');
  expect(screen.getByLabelText(/Исходник DAG/)).toHaveValue('{ broken'); expect(api.put).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Отменить изменение' }));
  expect(JSON.parse((screen.getByLabelText(/Исходник DAG/) as HTMLTextAreaElement).value)).toEqual(payload().data.current_version.dag);
});
it('preserves full source parameters through source-to-graph saving', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never); jest.mocked(api.put).mockResolvedValue({ data: {} } as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  const dag = payload().data.current_version.dag;
  dag.nodes[0].action = { type: 'http_request', url: 'https://example.com', headers: { 'X-Sphere': 'nested' } } as never;
  fireEvent.click(screen.getByRole('button', { name: 'JSON' }));
  fireEvent.change(screen.getByLabelText(/Исходник DAG/), { target: { value: JSON.stringify(dag) } });
  fireEvent.click(screen.getByRole('button', { name: 'Граф' }));
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/scripts/script-a', expect.objectContaining({ dag }), expect.any(Object)));
});
it('aborts stale validation on identity change and never shows its receipt in the next editor', async () => {
  const check = deferred<unknown>();
  jest.mocked(api.get).mockResolvedValue(payload() as never); jest.mocked(api.post).mockReturnValueOnce(check.promise as never);
  const view = render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на сервере' }));
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal;
  mockSessionVersion = 1; view.rerender(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  await act(async () => check.resolve({ data: { schema_version: 1, scope: 'structure-routes-lua-safety', device_execution_verified: false, node_count: 2, dag_hash: 'a'.repeat(64) } }));
  expect(signal?.aborted).toBe(true); expect(screen.queryByText(/Структура, переходы и безопасность/)).not.toBeInTheDocument();
  expect(api.put).not.toHaveBeenCalled();
});
it('does not enable publishing for an identity without a fresh write grant', async () => {
  mockCanWrite = false; jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  expect(screen.getByRole('button', { name: 'Сохранить версию' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Запустить версию' })).toBeDisabled();
});
it('restores a local draft explicitly without any API write', async () => {
  localStorage.setItem('sphere-studio-draft-v1:org-a:operator', JSON.stringify({ version: 1, resource: 'script-a', savedAt: Date.now(), name: 'Recovered', source: '{ fix me' }));
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Восстановить черновик' }));
  expect(screen.getByLabelText(/Исходник DAG/)).toHaveValue('{ fix me'); expect(screen.getByLabelText('Название сценария')).toHaveValue('Recovered');
  expect(api.put).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
});


it('blocks a repeated create after an unknown response while retaining export and source', async () => {
  mockEditId = null;
  jest.mocked(api.post).mockRejectedValueOnce(new Error('response lost after commit'));
  render(<ScriptBuilderPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Создать сценарий' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Результат сохранения неизвестен');
  expect(screen.getByRole('button', { name: 'Создать сценарий' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Создать сценарий' }));
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(mockPush).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Экспорт' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'JSON' }));
  expect(JSON.parse((screen.getByLabelText(/Исходник DAG 1.0/) as HTMLTextAreaElement).value).nodes[0]).toMatchObject({ id: 'start-1', action: { type: 'start' } });
});

it('keeps creation retry available after a definite API validation rejection', async () => {
  mockEditId = null;
  jest.mocked(api.post).mockRejectedValueOnce({ isAxiosError: true, response: { status: 422, data: { detail: 'invalid action parameter' } } });
  render(<ScriptBuilderPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Создать сценарий' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('invalid action parameter');
  expect(screen.getByRole('button', { name: 'Создать сценарий' })).toBeEnabled();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('honors owned-workbench guard on save, editor exit and native page unload', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />);
  expect(await screen.findByText('script-a-start')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Устройство · запись · проверка' }));
  expect(screen.getByText('Owned workbench')).toBeInTheDocument();
  mockWorkbenchGuard.mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  fireEvent.click(screen.getByRole('button', { name: 'К каталогу сценариев' }));
  expect(api.put).not.toHaveBeenCalled(); expect(mockPush).not.toHaveBeenCalled();
  const unload = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(unload);
  expect(unload.defaultPrevented).toBe(true);
  expect(mockWorkbenchGuard).toHaveBeenLastCalledWith(true);
});

it('refits changed panels after measurement while retaining moved nodes and the canonical DAG', async () => {
  const frame = animationFrames();
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  jest.mocked(api.put).mockResolvedValue({ data: {} } as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  act(() => mockGraphProps.onNodesChange?.([{ id: 'script-a-start', type: 'position', position: { x: 73, y: 122 } }]));
  fireEvent.click(screen.getByRole('button', { name: 'Устройство · запись · проверка' }));
  expect(screen.getByText('Owned workbench')).toBeInTheDocument();
  expect(mockFitView).not.toHaveBeenCalled();
  frame(); expect(mockFitView).not.toHaveBeenCalled();
  frame(); expect(mockFitView).toHaveBeenCalledTimes(1);
  expect(mockFitView).toHaveBeenLastCalledWith(expect.objectContaining({ padding: expect.objectContaining({ top: '64px' }), maxZoom: 1 }));
  for (let event = 0; event < 3; event++) fireEvent.click(screen.getByRole('button', { name: 'Report workbench execution' }));
  fireEvent.change(screen.getByLabelText('Название сценария'), { target: { value: 'Renamed graph' } });
  frame(); frame(); expect(mockFitView).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Весь граф' }));
  expect(mockFitView).toHaveBeenLastCalledWith(expect.objectContaining({ minZoom: 0.15, maxZoom: 1 }));
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть устройство' }));
  frame(); frame(); expect(mockFitView).toHaveBeenCalledTimes(3);
  fireEvent.click(screen.getByRole('button', { name: 'Скрыть библиотеку действий' }));
  frame(); frame(); expect(mockFitView).toHaveBeenCalledTimes(4);
  fireEvent.click(screen.getByRole('button', { name: 'Показать библиотеку действий' }));
  frame(); frame(); expect(mockFitView).toHaveBeenCalledTimes(5);
  expect(mockGraphProps.nodes?.find(node => node.id === 'script-a-start')?.position).toEqual({ x: 73, y: 122 });
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить версию' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/scripts/script-a', expect.objectContaining({ name: 'Renamed graph', dag: payload().data.current_version.dag }), expect.any(Object)));
});

it('preserves unapplied node edits and only refits an accepted workbench close', async () => {
  const frame = animationFrames();
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'script-a-start' }));
  fireEvent.click(screen.getByRole('button', { name: 'JSON шага' }));
  const edited = JSON.stringify({ ...payload().data.current_version.dag.nodes[0], retry: 1 });
  fireEvent.change(screen.getByLabelText('Шаг JSON: action, переходы, retry, timeout_ms'), { target: { value: edited } });
  expect(mockGraphProps.nodesDraggable).toBe(false); expect(mockGraphProps.onNodesChange).toBeUndefined();
  fireEvent.click(screen.getByRole('button', { name: 'Устройство · запись · проверка' }));
  frame(); frame(); expect(mockFitView).toHaveBeenCalledTimes(1);
  mockWorkbenchGuard.mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть устройство' }));
  frame(); frame(); expect(mockFitView).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Owned workbench')).toBeInTheDocument();
  mockWorkbenchGuard.mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть устройство' }));
  frame(); frame(); expect(mockFitView).toHaveBeenCalledTimes(2);
  expect(mockGraphProps.nodesDraggable).toBe(false); expect(mockGraphProps.onNodesChange).toBeUndefined();
  expect(screen.getByRole('button', { name: 'Сохранить версию' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'JSON шага' }));
  expect(screen.getByLabelText('Шаг JSON: action, переходы, retry, timeout_ms')).toHaveValue(edited);
  expect(api.put).not.toHaveBeenCalled();
});

it('cancels a queued panel refit when leaving the graph before its canvas has settled', async () => {
  const frame = animationFrames();
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.click(screen.getByRole('button', { name: 'Устройство · запись · проверка' }));
  frame();
  fireEvent.click(screen.getByRole('button', { name: 'JSON' }));
  frame(); frame();
  expect(screen.queryByTestId('graph')).not.toBeInTheDocument();
  expect(mockFitView).not.toHaveBeenCalled();
});

it('retains unapplied node parameters until explicit cancellation instead of losing them through undo or redo', async () => {
  jest.mocked(api.get).mockResolvedValue(payload() as never);
  render(<ScriptBuilderPage />); await screen.findByText('script-a-start');
  fireEvent.change(screen.getByLabelText('Название сценария'), { target: { value: 'First edit' } });
  fireEvent.change(screen.getByLabelText('Название сценария'), { target: { value: 'Second edit' } });
  fireEvent.click(screen.getByRole('button', { name: 'Отменить изменение' }));
  expect(screen.getByLabelText('Название сценария')).toHaveValue('First edit');
  fireEvent.click(screen.getByRole('button', { name: 'Граф' }));
  fireEvent.click(screen.getByRole('button', { name: 'script-a-start' }));
  fireEvent.click(screen.getByRole('button', { name: 'JSON шага' }));
  const pending = JSON.stringify({ ...payload().data.current_version.dag.nodes[0], retry: 2 });
  fireEvent.change(screen.getByLabelText('Шаг JSON: action, переходы, retry, timeout_ms'), { target: { value: pending } });
  const undo = screen.getByRole('button', { name: 'Отменить изменение' });
  const redo = screen.getByRole('button', { name: 'Повторить изменение' });
  expect(undo).toBeDisabled(); expect(redo).toBeDisabled();
  fireEvent.click(undo); fireEvent.click(redo);
  expect(screen.getByLabelText('Шаг JSON: action, переходы, retry, timeout_ms')).toHaveValue(pending);
  expect(screen.getByLabelText('Название сценария')).toHaveValue('First edit');
  expect(api.put).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Отменить параметры' }));
  expect(undo).toBeEnabled(); expect(redo).toBeEnabled();
  fireEvent.click(redo);
  expect(screen.getByLabelText('Название сценария')).toHaveValue('Second edit');
});
