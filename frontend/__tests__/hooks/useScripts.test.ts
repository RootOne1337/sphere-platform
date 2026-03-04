/**
 * Тесты хуков скриптов — CRUD, версии, архивация, откат.
 * Покрытие: useScripts, useScript, useScriptVersions, useCreateScript,
 * useUpdateScript, useArchiveScript, useRollbackScript.
 */
import { waitFor } from '@testing-library/react';
import { renderQueryHook } from '../helpers';
import {
  useScripts,
  useScript,
  useScriptVersions,
  useCreateScript,
  useUpdateScript,
  useArchiveScript,
  useRollbackScript,
} from '@/lib/hooks/useScripts';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
}));

const mockApi = api as jest.Mocked<typeof api>;

const MOCK_SCRIPT = {
  id: 'scr-001',
  name: 'Авторизация',
  description: 'Сценарий авторизации в приложении',
  is_archived: false,
  node_count: 12,
  created_at: '2026-01-15T10:00:00Z',
  updated_at: '2026-03-01T15:30:00Z',
};

const MOCK_SCRIPTS_RESPONSE = {
  items: [MOCK_SCRIPT],
  total: 1,
  page: 1,
  per_page: 20,
};

const MOCK_DAG = { nodes: { start: { type: 'start' } }, edges: [] };

const MOCK_SCRIPT_DETAIL = {
  ...MOCK_SCRIPT,
  dag: MOCK_DAG,
  current_version: 3,
  versions: [
    {
      id: 'ver-003',
      script_id: 'scr-001',
      version: 3,
      dag: MOCK_DAG,
      dag_hash: 'abc123',
      notes: 'Добавлен watchdog',
      created_by_id: 'user-001',
      created_at: '2026-03-01T15:30:00Z',
    },
  ],
};

const MOCK_VERSIONS = [
  {
    id: 'ver-001',
    script_id: 'scr-001',
    version: 1,
    dag: null,
    dag_hash: 'hash1',
    notes: 'Начальная версия',
    created_by_id: 'user-001',
    created_at: '2026-01-15T10:00:00Z',
  },
  {
    id: 'ver-002',
    script_id: 'scr-001',
    version: 2,
    dag: null,
    dag_hash: 'hash2',
    notes: 'Фикс условия',
    created_by_id: 'user-001',
    created_at: '2026-02-10T12:00:00Z',
  },
];

describe('useScripts', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает список скриптов с пагинацией', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_SCRIPTS_RESPONSE });

    const { result } = renderQueryHook(() => useScripts({ page: 1, per_page: 20 }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.total).toBe(1);
  });

  it('обрабатывает ответ-массив (обратная совместимость)', async () => {
    // Бекенд может вернуть просто массив
    mockApi.get.mockResolvedValueOnce({ data: [MOCK_SCRIPT] });

    const { result } = renderQueryHook(() => useScripts());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.page).toBe(1);
  });

  it('передаёт параметр поиска', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_SCRIPTS_RESPONSE });

    renderQueryHook(() => useScripts({ query: 'авториз' }));

    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    expect(mockApi.get).toHaveBeenCalledWith('/scripts', {
      params: { query: 'авториз' },
    });
  });
});

describe('useScript', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает детали скрипта с DAG', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_SCRIPT_DETAIL });

    const { result } = renderQueryHook(() => useScript('scr-001'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.dag).toEqual(MOCK_DAG);
    expect(result.current.data?.current_version).toBe(3);
  });

  it('не делает запрос при пустом scriptId', async () => {
    renderQueryHook(() => useScript(''));

    // Ждём один tick — запрос не должен уйти
    await new Promise((r) => setTimeout(r, 50));
    expect(mockApi.get).not.toHaveBeenCalled();
  });

  it('передаёт include_dag параметр', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_SCRIPT_DETAIL });

    renderQueryHook(() => useScript('scr-001', { includeDag: false }));

    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    expect(mockApi.get).toHaveBeenCalledWith('/scripts/scr-001', {
      params: { include_dag: false },
    });
  });
});

describe('useScriptVersions', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает историю версий скрипта', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_VERSIONS });

    const { result } = renderQueryHook(() => useScriptVersions('scr-001'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
    expect(result.current.data?.[1].version).toBe(2);
  });

  it('не делает запрос при пустом scriptId', async () => {
    renderQueryHook(() => useScriptVersions(''));

    await new Promise((r) => setTimeout(r, 50));
    expect(mockApi.get).not.toHaveBeenCalled();
  });
});

describe('useCreateScript', () => {
  beforeEach(() => jest.clearAllMocks());

  it('создаёт скрипт с DAG', async () => {
    mockApi.post.mockResolvedValueOnce({ data: MOCK_SCRIPT });

    const { result } = renderQueryHook(() => useCreateScript());

    result.current.mutate({
      name: 'Авторизация',
      description: 'Сценарий авторизации',
      dag: MOCK_DAG,
      changelog: 'Начальная версия',
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/scripts', {
      name: 'Авторизация',
      description: 'Сценарий авторизации',
      dag: MOCK_DAG,
      changelog: 'Начальная версия',
    });
  });
});

describe('useUpdateScript', () => {
  beforeEach(() => jest.clearAllMocks());

  it('обновляет скрипт по ID (PUT /scripts/{id})', async () => {
    mockApi.put.mockResolvedValueOnce({ data: { ...MOCK_SCRIPT, name: 'Обновлённый' } });

    const { result } = renderQueryHook(() => useUpdateScript());

    result.current.mutate({
      scriptId: 'scr-001',
      name: 'Обновлённый',
      dag: MOCK_DAG,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.put).toHaveBeenCalledWith('/scripts/scr-001', {
      name: 'Обновлённый',
      dag: MOCK_DAG,
    });
  });
});

describe('useArchiveScript', () => {
  beforeEach(() => jest.clearAllMocks());

  it('архивирует скрипт DELETE /scripts/{id}', async () => {
    mockApi.delete.mockResolvedValueOnce({ data: null });

    const { result } = renderQueryHook(() => useArchiveScript());

    result.current.mutate('scr-001');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.delete).toHaveBeenCalledWith('/scripts/scr-001');
  });
});

describe('useRollbackScript', () => {
  beforeEach(() => jest.clearAllMocks());

  it('откатывает скрипт к указанной версии', async () => {
    mockApi.post.mockResolvedValueOnce({ data: MOCK_SCRIPT });

    const { result } = renderQueryHook(() => useRollbackScript());

    result.current.mutate({ scriptId: 'scr-001', versionId: 'ver-001' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/scripts/scr-001/versions/ver-001/rollback');
  });
});
