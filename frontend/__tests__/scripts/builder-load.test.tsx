import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import ScriptBuilderPage from '@/app/(dashboard)/scripts/builder/page';
import { api } from '@/lib/api';

let mockEditId: string | null = 'script-a';
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(mockEditId ? { id: mockEditId } : {}),
}));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), put: jest.fn(), post: jest.fn() } }));
jest.mock('@/lib/dag/nodeTypes', () => ({ nodeTypes: {} }));
jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => null }));
jest.mock('@xyflow/react/dist/style.css', () => ({}));
jest.mock('@xyflow/react', () => {
  const React = jest.requireActual('react');
  return {
    useNodesState: (initial: unknown) => [...React.useState(initial), jest.fn()],
    useEdgesState: (initial: unknown) => [...React.useState(initial), jest.fn()],
    addEdge: jest.fn(),
    ReactFlow: ({ nodes }: { nodes: { id: string }[] }) => (
      <div data-testid="graph">{nodes.map((node) => <span key={node.id}>{node.id}</span>)}</div>
    ),
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

beforeEach(() => { jest.clearAllMocks(); mockEditId = 'script-a'; });

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
  }));
  expect(api.post).not.toHaveBeenCalled();
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
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/scripts/script-b', expect.objectContaining({ name: 'B graph' })));
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
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/scripts', expect.objectContaining({ dag: expect.any(Object) })));
  expect(api.get).not.toHaveBeenCalled();
  expect(api.put).not.toHaveBeenCalled();
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
  expect(screen.getByTestId('graph')).toBeInTheDocument();
  expect(mockPush).not.toHaveBeenCalled();
});
