/**
 * Тесты хука useDevices — запросы и мутации управления устройствами.
 * Покрытие: useDevices, useBulkAction, useUpdateDevice, useDeleteDevice, useBulkDeleteDevices.
 */
import { waitFor } from '@testing-library/react';
import { renderQueryHook, createTestQueryClient } from '../helpers';
import {
  useDevices,
  useBulkAction,
  useUpdateDevice,
  useDeleteDevice,
  useBulkDeleteDevices,
} from '@/lib/hooks/useDevices';
import { api } from '@/lib/api';

// ── Мокируем HTTP-клиент ────────────────────────────────────────────────────
jest.mock('@/lib/api', () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
  },
}));

const mockApi = api as jest.Mocked<typeof api>;

const MOCK_DEVICES_RESPONSE = {
  items: [
    {
      id: 'dev-001',
      name: 'Pixel 7',
      android_id: 'abc123',
      model: 'Pixel 7',
      device_model: null,
      android_version: '14',
      tags: ['production'],
      group_id: null,
      group_ids: [],
      group_name: null,
      location_ids: [],
      status: 'online' as const,
      battery_level: 85,
      cpu_usage: 12.5,
      ram_usage_mb: 512,
      screen_on: true,
      last_seen: '2026-03-04T10:00:00Z',
      last_heartbeat: '2026-03-04T10:00:00Z',
      adb_connected: true,
      vpn_assigned: false,
      vpn_active: null,
    },
  ],
  total: 1,
  page: 1,
  page_size: 20,
};

describe('useDevices', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает список устройств с параметрами', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_DEVICES_RESPONSE });

    const { result } = renderQueryHook(() => useDevices({ page: 1, page_size: 20, search: 'Pixel' }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mockApi.get).toHaveBeenCalledWith('/devices', {
      params: expect.objectContaining({ page: 1, per_page: 20, search: 'Pixel' }),
    });
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.items[0].name).toBe('Pixel 7');
  });

  it('возвращает ошибку при неудачном запросе', async () => {
    mockApi.get.mockRejectedValueOnce(new Error('Network Error'));

    const { result } = renderQueryHook(() => useDevices({}));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeDefined();
  });

  it('маппит page_size → per_page для бекенда', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_DEVICES_RESPONSE });

    renderQueryHook(() => useDevices({ page_size: 50 }));

    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    const params = mockApi.get.mock.calls[0][1]?.params;
    expect(params.per_page).toBe(50);
    expect(params.page_size).toBeUndefined();
  });
});

describe('useBulkAction', () => {
  beforeEach(() => jest.clearAllMocks());

  it('отправляет bulk action на устройства', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { success: true } });
    const qc = createTestQueryClient();

    const { result } = renderQueryHook(() => useBulkAction(), { queryClient: qc });

    result.current.mutate({
      device_ids: ['dev-001', 'dev-002'],
      action: 'reboot',
      params: { force: true },
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/devices/bulk/action', {
      device_ids: ['dev-001', 'dev-002'],
      action: 'reboot',
      params: { force: true },
    });
  });
});

describe('useUpdateDevice', () => {
  beforeEach(() => jest.clearAllMocks());

  it('обновляет имя и теги устройства', async () => {
    mockApi.put.mockResolvedValueOnce({ data: { id: 'dev-001', name: 'New Name' } });

    const { result } = renderQueryHook(() => useUpdateDevice());

    result.current.mutate({ id: 'dev-001', name: 'New Name', tags: ['test'] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.put).toHaveBeenCalledWith('/devices/dev-001', {
      name: 'New Name',
      tags: ['test'],
    });
  });
});

describe('useDeleteDevice', () => {
  beforeEach(() => jest.clearAllMocks());

  it('удаляет устройство по ID', async () => {
    mockApi.delete.mockResolvedValueOnce({ data: null });

    const { result } = renderQueryHook(() => useDeleteDevice());

    result.current.mutate('dev-001');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.delete).toHaveBeenCalledWith('/devices/dev-001');
  });
});

describe('useBulkDeleteDevices', () => {
  beforeEach(() => jest.clearAllMocks());

  it('удаляет пачку устройств одним запросом', async () => {
    mockApi.delete.mockResolvedValueOnce({ data: { deleted: 3 } });

    const { result } = renderQueryHook(() => useBulkDeleteDevices());

    result.current.mutate(['dev-001', 'dev-002', 'dev-003']);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.delete).toHaveBeenCalledWith('/devices/bulk', {
      data: { device_ids: ['dev-001', 'dev-002', 'dev-003'] },
    });
    expect(result.current.data?.deleted).toBe(3);
  });

  it('обрабатывает ошибку при удалении', async () => {
    mockApi.delete.mockRejectedValueOnce(new Error('Forbidden'));

    const { result } = renderQueryHook(() => useBulkDeleteDevices());

    result.current.mutate(['dev-001']);

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
