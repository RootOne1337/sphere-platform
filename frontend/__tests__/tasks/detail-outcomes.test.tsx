import { Suspense } from 'react';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TaskDetailPage from '@/app/(dashboard)/tasks/[id]/page';
import { api } from '@/lib/api';
import { type NodeExecutionLog, type TaskDetail } from '@/lib/hooks/useTasks';
import { createTestQueryClient, createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));

function task(overrides: Partial<TaskDetail> = {}): TaskDetail {
  return {
    id: 'task-a', org_id: 'org', script_id: 'script', device_id: 'device',
    script_version_id: 'version-1', batch_id: null, status: 'running', priority: 5,
    started_at: '2026-10-01T00:00:00Z', finished_at: null, wave_index: null,
    created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
    device_name: 'Remote Android', script_name: 'Audit script', result: null,
    error_message: null, input_params: null, ...overrides,
  };
}

function report(node_id: string, success: boolean): NodeExecutionLog {
  return { node_id, success, action_type: 'tap', duration_ms: 30, started_at: null,
    screenshot_key: null, error: success ? null : 'Element missing', output: null };
}

it('offers an authenticated screenshot read rather than guessing a public files path', async () => {
  current = task({ status: 'completed' });
  readLogs = async () => ({ data: [{ ...report('capture', true), screenshot_key: 'tasks/task-a/device/capture/123.jpg' }] });
  await openPage();
  expect(await screen.findByRole('button', { name: 'Открыть снимок шага' })).toBeEnabled();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

let current: TaskDetail;
let readTask: () => Promise<{ data: TaskDetail }>;
let readLogs: () => Promise<{ data: NodeExecutionLog[] }>;
beforeEach(() => {
  jest.clearAllMocks();
  current = task();
  readTask = async () => ({ data: current });
  readLogs = async () => ({ data: [] });
  jest.mocked(api.get).mockImplementation((url) => {
    if (url === '/tasks/task-a' || url === '/tasks/task-b') return readTask() as never;
    if (url.endsWith('/logs')) return readLogs() as never;
    if (url.endsWith('/progress')) return Promise.resolve({ data: { nodes_done: 20, total_nodes: 3, cycles: 2, current_node: 'tap', started_at: null } }) as never;
    return Promise.resolve({ data: [] }) as never;
  });
  jest.mocked(api.post).mockResolvedValue({ data: { id: 'task-new', status: 'queued' } } as never);
  jest.mocked(api.delete).mockResolvedValue({} as never);
});

async function openPage(client = createTestQueryClient(), id = 'task-a') {
  const params = Promise.resolve({ id });
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(<Suspense fallback={<p>Loading route</p>}><TaskDetailPage params={params} /></Suspense>, { wrapper: createWrapper(client) });
    await params;
  });
  await waitFor(() => expect(screen.queryByText('Loading route')).not.toBeInTheDocument());
  return { client, view };
}

it.each([
  [404, 'Задание не найдено'],
  [401, 'Требуется вход в систему'],
  [403, 'Нет доступа к заданию'],
  [undefined, 'Не удалось загрузить задание'],
])('distinguishes HTTP %s from a missing task and exposes an explicit retry', async (status, title) => {
  readTask = async () => { throw { response: { status } }; };
  await openPage();
  expect(await screen.findByRole('alert')).toHaveTextContent(title);
  if (status !== 404) expect(screen.queryByText('API подтвердил отсутствие записи.')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Остановить задание' })).not.toBeInTheDocument();
  readTask = async () => ({ data: current });
  await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку задания' }));
  expect(await screen.findByRole('button', { name: 'Остановить задание' })).toBeEnabled();
});

it('rejects a response owned by another task before enabling commands', async () => {
  current = task({ id: 'task-b' });
  await openPage();
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить задание');
  expect(screen.queryByText('task-b')).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('counts success and failure reports instead of inventing 100% from the progress counter', async () => {
  readLogs = async () => ({ data: [report('step-one', true), report('step-two', false)] });
  await openPage();
  const metric = (await screen.findByText('Успешные отчёты')).parentElement!;
  await waitFor(() => expect(within(metric).getByText('1/2')).toBeInTheDocument());
  expect(screen.queryByText('Pass Rate')).not.toBeInTheDocument();
  expect(screen.queryByText('100%')).not.toBeInTheDocument();
  expect(screen.getByText(/полнота выполнения по ним не подтверждается/)).toBeInTheDocument();
});

it('does not infer successful execution or completed cycles from an empty report set', async () => {
  jest.mocked(api.get).mockImplementation((url) => {
    if (url === '/tasks/task-a') return readTask() as never;
    if (url.endsWith('/progress')) return Promise.reject(new Error('Redis unavailable'));
    return Promise.resolve({ data: [] }) as never;
  });
  current = task({ result: { nodes_executed: 50, total_nodes: 3 } });
  await openPage();
  expect(await screen.findByText('Нет отчётов')).toBeInTheDocument();
  const cycles = screen.getByText('Циклы').parentElement!;
  expect(within(cycles).getByText('—')).toBeInTheDocument();
  expect(screen.queryByText('100%')).not.toBeInTheDocument();
  expect(await screen.findByText(/Не удалось обновить прогресс/)).toBeInTheDocument();
});

it('describes received terminal reports without labeling all executed nodes as passed', async () => {
  current = task({ status: 'failed', result: { nodes_executed: 20, total_nodes: 3 } });
  readLogs = async () => ({ data: [report('repeated', true), report('repeated', false)] });
  await openPage();
  expect(await screen.findByText('1 успешных · 1 ошибок · 2 получено')).toBeInTheDocument();
  expect(screen.queryByText('20 passed')).not.toBeInTheDocument();
  expect(screen.getByText('Element missing')).toBeInTheDocument();
});

it('blocks stale task commands after a refresh failure and allows them again after explicit recovery', async () => {
  const { client } = await openPage();
  await screen.findByRole('button', { name: 'Остановить задание' });
  readTask = async () => { throw { response: { status: 403 } }; };
  await act(async () => { await client.refetchQueries({ queryKey: ['tasks', 'task-a'], exact: true }); });
  expect(await screen.findByRole('alert')).toHaveTextContent('Нет доступа к заданию');
  expect(screen.getByRole('button', { name: 'Остановить задание' })).toBeDisabled();
  expect(screen.getByText('Remote Android')).toBeInTheDocument();
  readTask = async () => ({ data: current });
  await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку задания' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Остановить задание' })).toBeEnabled());
});

it.each([
  ['running', 'Остановить задание', 'post'],
  ['queued', 'Отменить задание', 'delete'],
  ['failed', 'Повторить выполнение', 'post'],
])('shows a failed %s command and permits a retry without pretending it succeeded', async (status, button, method) => {
  current = task({ status });
  jest.mocked(api[method as 'post' | 'delete']).mockRejectedValueOnce({ response: { data: { detail: 'Permission denied by API' } } });
  await openPage();
  await userEvent.click(await screen.findByRole('button', { name: button }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Permission denied by API');
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: button })).toBeEnabled();
  await userEvent.click(screen.getByRole('button', { name: button }));
  expect(await screen.findByRole('status')).toHaveTextContent(/приня[лт]/);
  expect(screen.queryByText('Permission denied by API')).not.toBeInTheDocument();
});

it('links the server-created task receipt and does not claim execution completed', async () => {
  current = task({ status: 'completed' });
  await openPage();
  await userEvent.click(await screen.findByRole('button', { name: 'Повторить выполнение' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Результат выполнения ещё не подтверждён');
  expect(screen.getByRole('link', { name: 'Открыть новое задание' })).toHaveAttribute('href', '/tasks/task-new');
  expect(api.post).toHaveBeenCalledWith('/tasks/task-a/rerun');
});

it('disables a legacy rerun when the original version is not recorded', async () => {
  current = task({ status: 'failed', script_version_id: null });
  await openPage();
  expect(await screen.findByRole('button', { name: 'Повторить выполнение' })).toBeDisabled();
  expect(screen.getByText('неизвестна — повтор недоступен')).toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('reports failed log reads without a fictional empty timeline and can recover', async () => {
  current = task({ status: 'failed' });
  readLogs = async () => { throw new Error('Log store unavailable'); };
  await openPage();
  expect(await screen.findByRole('alert')).toHaveTextContent('Отсутствие отчётов не подтверждено');
  expect(screen.queryByText('Отчёты шагов не получены.')).not.toBeInTheDocument();
  readLogs = async () => ({ data: [report('recovered-step', false)] });
  await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку отчётов' }));
  expect(await screen.findByText('recovered-step')).toBeInTheDocument();
});

it('marks fallback result logs as a snapshot while the log endpoint is unavailable', async () => {
  current = task({ status: 'failed', result: { node_logs: [report('saved-step', false)] } });
  readLogs = async () => { throw new Error('Log store unavailable'); };
  await openPage();
  expect(await screen.findByText('saved-step')).toBeInTheDocument();
  expect(screen.getByText('Источник: последний снимок результата задания.')).toBeInTheDocument();
  expect(await screen.findByRole('alert')).toHaveTextContent('Показаны ранее полученные данные');
});

it('isolates command errors across task changes and cancels the old resource GET', async () => {
  const old = deferred<{ data: TaskDetail }>();
  readTask = () => old.promise;
  const { view } = await openPage();
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/tasks/task-a', expect.anything()));
  const signal = jest.mocked(api.get).mock.calls.find(([url]) => url === '/tasks/task-a')?.[1]?.signal;
  current = task({ id: 'task-b', status: 'completed' });
  readTask = async () => ({ data: current });
  const params = Promise.resolve({ id: 'task-b' });
  await act(async () => {
    view.rerender(<Suspense fallback={<p>Loading route</p>}><TaskDetailPage params={params} /></Suspense>);
    await params;
  });
  expect(await screen.findByText('task-b')).toBeInTheDocument();
  await waitFor(() => expect(signal?.aborted).toBe(true));
  await act(async () => old.resolve({ data: task() }));
  expect(screen.queryByRole('button', { name: 'Остановить задание' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Повторить выполнение' })).toBeEnabled();
});

it('uses final result counts after an active run completes and stops its elapsed time', async () => {
  const { client } = await openPage();
  await waitFor(() => expect(within(screen.getByText('Выполнено узлов').parentElement!).getByText('20')).toBeInTheDocument());
  expect(screen.getByText('Текущий узел')).toBeInTheDocument();
  expect(screen.getByRole('complementary', { name: 'Журнал выполнения' })).toBeInTheDocument();

  current = task({ status: 'completed', finished_at: '2026-10-01T00:00:05Z', result: { nodes_executed: 2, total_nodes: 9, cycles: 4 } });
  await act(async () => { await client.refetchQueries({ queryKey: ['tasks', 'task-a'], exact: true }); });

  expect(await screen.findByRole('region', { name: 'Итог выполнения' })).toBeInTheDocument();
  expect(within(screen.getByText('Выполнено узлов').parentElement!).getByText('2')).toBeInTheDocument();
  expect(within(screen.getByText('Всего узлов').parentElement!).getByText('9')).toBeInTheDocument();
  expect(within(screen.getByText('Циклы').parentElement!).getByText('4')).toBeInTheDocument();
  expect(within(screen.getByText('Длительность').closest('dl')!).getByText('00:00:05')).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Итог выполнения' })).getByText('00:00:05')).toBeInTheDocument();
  expect(screen.queryByText('Текущий узел')).not.toBeInTheDocument();
  expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Все задания' })).toHaveAttribute('href', '/tasks');
});

it('does not use cached progress or an advancing duration when the terminal result is incomplete', async () => {
  const client = createTestQueryClient();
  client.setQueryData(['tasks', 'task-a', 'progress'], { nodes_done: 88, total_nodes: 99, cycles: 7, current_node: 'stale-node', started_at: 1 });
  current = task({ status: 'failed' });
  readLogs = async () => ({ data: [report('received-step', true)] });
  await openPage(client);

  for (const label of ['Выполнено узлов', 'Всего узлов', 'Циклы']) {
    expect(within(screen.getByText(label).parentElement!).getByText('—')).toBeInTheDocument();
  }
  expect(within(screen.getByText('Длительность').closest('dl')!).getByText('—')).toBeInTheDocument();
  expect(await screen.findByText('received-step')).toBeInTheDocument();
  expect(screen.getByText('1 успешных · 0 ошибок · 1 получено')).toBeInTheDocument();
  expect(screen.queryByText('stale-node')).not.toBeInTheDocument();
  expect(api.get).not.toHaveBeenCalledWith('/tasks/task-a/progress', expect.anything());
});

it.each(['running', 'queued', 'assigned'])('keeps a pending %s cancellation separate from a confirmed outcome', async status => {
  current = task({ status, cancel_requested_at: '2026-10-01T00:00:02Z' });
  await openPage();
  expect(await screen.findByText('Отмена: ожидается результат устройства')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Ожидается результат' })).toBeDisabled();
  expect(screen.queryByText('Отменено')).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
  expect(api.delete).not.toHaveBeenCalled();
});

it('keeps a timeout cancellation request awaiting the device result', async () => {
  current = task({ cancel_requested_at: '2026-10-01T00:00:02Z', timeout_requested_at: '2026-10-01T00:00:02Z' });
  await openPage();
  expect(await screen.findByText('Таймаут: ожидается результат устройства')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Ожидается результат' })).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'Повторить выполнение' })).not.toBeInTheDocument();
});
