/**
 * Тесты хуков Event Triggers — CRUD + toggle.
 * Покрытие: useEventTriggers, useCreateEventTrigger, useUpdateEventTrigger,
 * useToggleEventTrigger, useDeleteEventTrigger.
 *
 * Уровень: Enterprise — проверяем все мутации, пагинацию, фильтрацию, ошибки API.
 */
import { waitFor, act } from '@testing-library/react';
import { renderQueryHook } from '../helpers';
import {
  useEventTriggers,
  useCreateEventTrigger,
  useUpdateEventTrigger,
  useToggleEventTrigger,
  useDeleteEventTrigger,
  type EventTrigger,
} from '@/lib/hooks/useEventTriggers';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    patch: jest.fn(),
    delete: jest.fn(),
  },
}));

const mockApi = api as jest.Mocked<typeof api>;

// ── Фикстуры ─────────────────────────────────────────────────────────

const MOCK_TRIGGER: EventTrigger = {
  id: 'trig-001',
  org_id: 'org-001',
  name: 'Бан → Ротация',
  description: 'Авто-ротация аккаунта при бане',
  event_type_pattern: 'account.banned',
  pipeline_id: 'pipe-001',
  input_params_template: { device_id: '{device_id}' },
  is_active: true,
  cooldown_seconds: 60,
  max_triggers_per_hour: 100,
  last_triggered_at: '2026-03-06T10:00:00Z',
  total_triggers: 42,
  created_at: '2026-03-05T12:00:00Z',
  updated_at: '2026-03-06T10:00:00Z',
};

const MOCK_TRIGGER_2: EventTrigger = {
  id: 'trig-002',
  org_id: 'org-001',
  name: 'Офлайн → Алерт',
  description: null,
  event_type_pattern: 'device.offline',
  pipeline_id: 'pipe-002',
  input_params_template: {},
  is_active: false,
  cooldown_seconds: 300,
  max_triggers_per_hour: 10,
  last_triggered_at: null,
  total_triggers: 0,
  created_at: '2026-03-05T13:00:00Z',
  updated_at: '2026-03-05T13:00:00Z',
};

const MOCK_LIST_RESPONSE = {
  items: [MOCK_TRIGGER, MOCK_TRIGGER_2],
  total: 2,
  page: 1,
  per_page: 100,
  pages: 1,
};

// ══════════════════════════════════════════════════════════════════════
//  useEventTriggers — списковый хук
// ══════════════════════════════════════════════════════════════════════

describe('useEventTriggers', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает список триггеров', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_LIST_RESPONSE });

    const { result } = renderQueryHook(() => useEventTriggers());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(2);
    expect(result.current.data?.total).toBe(2);
    expect(mockApi.get).toHaveBeenCalledWith('/event-triggers', { params: {} });
  });

  it('передаёт фильтры в query params', async () => {
    mockApi.get.mockResolvedValueOnce({ data: { ...MOCK_LIST_RESPONSE, items: [MOCK_TRIGGER] } });

    const { result } = renderQueryHook(() =>
      useEventTriggers({ is_active: true, per_page: 50 }),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.get).toHaveBeenCalledWith('/event-triggers', {
      params: { is_active: true, per_page: 50 },
    });
  });

  it('корректно обрабатывает пустой ответ', async () => {
    mockApi.get.mockResolvedValueOnce({
      data: { items: [], total: 0, page: 1, per_page: 100, pages: 0 },
    });

    const { result } = renderQueryHook(() => useEventTriggers());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(0);
    expect(result.current.data?.total).toBe(0);
  });

  it('выставляет isError при сбое API', async () => {
    mockApi.get.mockRejectedValueOnce(new Error('Network Error'));

    const { result } = renderQueryHook(() => useEventTriggers());

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ══════════════════════════════════════════════════════════════════════
//  useCreateEventTrigger — создание
// ══════════════════════════════════════════════════════════════════════

describe('useCreateEventTrigger', () => {
  beforeEach(() => jest.clearAllMocks());

  it('создаёт триггер через POST /event-triggers', async () => {
    const newTrigger = { ...MOCK_TRIGGER, id: 'trig-new' };
    mockApi.post.mockResolvedValueOnce({ data: newTrigger });

    const { result } = renderQueryHook(() => useCreateEventTrigger());

    await act(async () => {
      result.current.mutate({
        name: 'Бан → Ротация',
        event_type_pattern: 'account.banned',
        pipeline_id: 'pipe-001',
        cooldown_seconds: 60,
        max_triggers_per_hour: 100,
        input_params_template: { device_id: '{device_id}' },
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/event-triggers', {
      name: 'Бан → Ротация',
      event_type_pattern: 'account.banned',
      pipeline_id: 'pipe-001',
      cooldown_seconds: 60,
      max_triggers_per_hour: 100,
      input_params_template: { device_id: '{device_id}' },
    });
    expect(result.current.data?.id).toBe('trig-new');
  });

  it('обрабатывает ошибку 422 (невалидные данные)', async () => {
    mockApi.post.mockRejectedValueOnce({
      response: { status: 422, data: { detail: 'Pipeline не найден' } },
    });

    const { result } = renderQueryHook(() => useCreateEventTrigger());

    await act(async () => {
      result.current.mutate({
        name: 'Test',
        event_type_pattern: 'test.*',
        pipeline_id: 'nonexistent',
      });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ══════════════════════════════════════════════════════════════════════
//  useUpdateEventTrigger — обновление
// ══════════════════════════════════════════════════════════════════════

describe('useUpdateEventTrigger', () => {
  beforeEach(() => jest.clearAllMocks());

  it('обновляет триггер через PATCH /event-triggers/{id}', async () => {
    const updated = { ...MOCK_TRIGGER, name: 'Бан → Алерт' };
    mockApi.patch.mockResolvedValueOnce({ data: updated });

    const { result } = renderQueryHook(() => useUpdateEventTrigger());

    await act(async () => {
      result.current.mutate({ id: 'trig-001', name: 'Бан → Алерт' });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.patch).toHaveBeenCalledWith('/event-triggers/trig-001', {
      name: 'Бан → Алерт',
    });
    expect(result.current.data?.name).toBe('Бан → Алерт');
  });

  it('обновляет cooldown и max_triggers_per_hour', async () => {
    const updated = { ...MOCK_TRIGGER, cooldown_seconds: 120, max_triggers_per_hour: 50 };
    mockApi.patch.mockResolvedValueOnce({ data: updated });

    const { result } = renderQueryHook(() => useUpdateEventTrigger());

    await act(async () => {
      result.current.mutate({ id: 'trig-001', cooldown_seconds: 120, max_triggers_per_hour: 50 });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.cooldown_seconds).toBe(120);
  });
});

// ══════════════════════════════════════════════════════════════════════
//  useToggleEventTrigger — переключение is_active
// ══════════════════════════════════════════════════════════════════════

describe('useToggleEventTrigger', () => {
  beforeEach(() => jest.clearAllMocks());

  it('переключает активность через POST /event-triggers/{id}/toggle', async () => {
    const toggled = { ...MOCK_TRIGGER, is_active: false };
    mockApi.post.mockResolvedValueOnce({ data: toggled });

    const { result } = renderQueryHook(() => useToggleEventTrigger());

    await act(async () => {
      result.current.mutate('trig-001');
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/event-triggers/trig-001/toggle');
    expect(result.current.data?.is_active).toBe(false);
  });

  it('обрабатывает ошибку 404', async () => {
    mockApi.post.mockRejectedValueOnce({
      response: { status: 404, data: { detail: 'Триггер не найден' } },
    });

    const { result } = renderQueryHook(() => useToggleEventTrigger());

    await act(async () => {
      result.current.mutate('nonexistent-id');
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ══════════════════════════════════════════════════════════════════════
//  useDeleteEventTrigger — удаление
// ══════════════════════════════════════════════════════════════════════

describe('useDeleteEventTrigger', () => {
  beforeEach(() => jest.clearAllMocks());

  it('удаляет триггер через DELETE /event-triggers/{id}', async () => {
    mockApi.delete.mockResolvedValueOnce({});

    const { result } = renderQueryHook(() => useDeleteEventTrigger());

    await act(async () => {
      result.current.mutate('trig-001');
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.delete).toHaveBeenCalledWith('/event-triggers/trig-001');
  });

  it('обрабатывает ошибку 404 при удалении', async () => {
    mockApi.delete.mockRejectedValueOnce({
      response: { status: 404, data: { detail: 'Не найден' } },
    });

    const { result } = renderQueryHook(() => useDeleteEventTrigger());

    await act(async () => {
      result.current.mutate('nonexistent');
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
