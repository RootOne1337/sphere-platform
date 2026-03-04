/**
 * Тесты хуков задач — запросы, прогресс, live-логи, создание, отмена, остановка.
 * Покрытие: useTasks, useTask, useTaskLogs, useTaskProgress, useTaskLiveLogs,
 * useCreateTask, useCancelTask, useStopTask.
 */
import { waitFor } from '@testing-library/react';
import { renderQueryHook } from '../helpers';
import {
  useTasks,
  useTask,
  useTaskLogs,
  useTaskProgress,
  useTaskLiveLogs,
  useCreateTask,
  useCancelTask,
  useStopTask,
} from '@/lib/hooks/useTasks';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    delete: jest.fn(),
  },
}));

const mockApi = api as jest.Mocked<typeof api>;

const MOCK_TASK = {
  id: 'task-001',
  org_id: 'org-001',
  script_id: 'scr-001',
  device_id: 'dev-001',
  script_version_id: 'ver-003',
  batch_id: null,
  status: 'running',
  priority: 5,
  started_at: '2026-03-04T10:00:00Z',
  finished_at: null,
  wave_index: null,
  created_at: '2026-03-04T09:59:00Z',
  updated_at: '2026-03-04T10:01:00Z',
};

const MOCK_TASKS_RESPONSE = {
  items: [MOCK_TASK],
  total: 1,
  page: 1,
  per_page: 20,
  pages: 1,
};

const MOCK_TASK_DETAIL = {
  ...MOCK_TASK,
  result: { last_node: 'scan_all' },
  error_message: null,
  input_params: { priority: 5 },
};

const MOCK_LOGS = [
  {
    node_id: 'start',
    action_type: 'start',
    success: true,
    duration_ms: 5,
    started_at: '2026-03-04T10:00:00Z',
    screenshot_key: null,
    error: null,
    output: null,
  },
  {
    node_id: 'tap_login',
    action_type: 'tap',
    success: true,
    duration_ms: 120,
    started_at: '2026-03-04T10:00:01Z',
    screenshot_key: 'scr/task-001/tap_login.png',
    error: null,
    output: { x: 540, y: 1200 },
  },
];

const MOCK_PROGRESS = {
  nodes_done: 5,
  total_nodes: 12,
  current_node: 'input_password',
  progress: 0.4167,
  cycles: 1,
  started_at: 1709546400,
};

const MOCK_LIVE_LOGS = [
  { node_id: 'start', nodes_done: 1, ts: 1709546400 },
  { node_id: 'tap_login', nodes_done: 2, ts: 1709546401 },
];

describe('useTasks', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает список задач с фильтрами', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_TASKS_RESPONSE });

    const { result } = renderQueryHook(() =>
      useTasks({ page: 1, status: 'running', device_id: 'dev-001' }),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(mockApi.get).toHaveBeenCalledWith('/tasks', {
      params: { page: 1, status: 'running', device_id: 'dev-001' },
    });
  });

  it('возвращает пагинацию', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_TASKS_RESPONSE });

    const { result } = renderQueryHook(() => useTasks({}));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.total).toBe(1);
    expect(result.current.data?.pages).toBe(1);
  });
});

describe('useTask', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает детали задачи', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_TASK_DETAIL });

    const { result } = renderQueryHook(() => useTask('task-001'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.result).toEqual({ last_node: 'scan_all' });
  });

  it('не запрашивает при пустом taskId', async () => {
    renderQueryHook(() => useTask(''));

    await new Promise((r) => setTimeout(r, 50));
    expect(mockApi.get).not.toHaveBeenCalled();
  });
});

describe('useTaskLogs', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает логи выполнения нод', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_LOGS });

    const { result } = renderQueryHook(() => useTaskLogs('task-001'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
    expect(result.current.data?.[1].screenshot_key).toBe('scr/task-001/tap_login.png');
  });
});

describe('useTaskProgress', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает прогресс задачи при enabled=true', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_PROGRESS });

    const { result } = renderQueryHook(() => useTaskProgress('task-001', true));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.progress).toBeCloseTo(0.4167, 3);
    expect(result.current.data?.current_node).toBe('input_password');
  });

  it('не запрашивает при enabled=false', async () => {
    renderQueryHook(() => useTaskProgress('task-001', false));

    await new Promise((r) => setTimeout(r, 50));
    expect(mockApi.get).not.toHaveBeenCalled();
  });
});

describe('useTaskLiveLogs', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает live-логи при enabled=true', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_LIVE_LOGS });

    const { result } = renderQueryHook(() => useTaskLiveLogs('task-001', true));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
  });
});

describe('useCreateTask', () => {
  beforeEach(() => jest.clearAllMocks());

  it('создаёт задачу POST /tasks', async () => {
    mockApi.post.mockResolvedValueOnce({ data: MOCK_TASK });

    const { result } = renderQueryHook(() => useCreateTask());

    result.current.mutate({ script_id: 'scr-001', device_id: 'dev-001', priority: 5 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/tasks', {
      script_id: 'scr-001',
      device_id: 'dev-001',
      priority: 5,
    });
  });
});

describe('useCancelTask', () => {
  beforeEach(() => jest.clearAllMocks());

  it('отменяет задачу DELETE /tasks/{id}', async () => {
    mockApi.delete.mockResolvedValueOnce({ data: null });

    const { result } = renderQueryHook(() => useCancelTask());

    result.current.mutate('task-001');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.delete).toHaveBeenCalledWith('/tasks/task-001');
  });
});

describe('useStopTask', () => {
  beforeEach(() => jest.clearAllMocks());

  it('останавливает задачу POST /tasks/{id}/stop', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { status: 'stopped' } });

    const { result } = renderQueryHook(() => useStopTask());

    result.current.mutate('task-001');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/tasks/task-001/stop');
  });
});
