/**
 * Тесты хуков батчей — запуск, получение, отмена.
 * Покрытие: useStartBatch, useBatch, useCancelBatch.
 */
import { waitFor } from '@testing-library/react';
import { renderQueryHook } from '../helpers';
import {
  useStartBatch,
  useBatch,
  useCancelBatch,
} from '@/lib/hooks/useBatches';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    delete: jest.fn(),
  },
}));

const mockApi = api as jest.Mocked<typeof api>;

const MOCK_BATCH = {
  id: 'batch-001',
  org_id: 'org-001',
  script_id: 'scr-001',
  name: 'Ночной фарм',
  status: 'running',
  total: 50,
  succeeded: 20,
  failed: 1,
  wave_config: { wave_size: 10, wave_delay_ms: 5000 },
  created_at: '2026-03-04T02:00:00Z',
  updated_at: '2026-03-04T02:30:00Z',
};

describe('useStartBatch', () => {
  beforeEach(() => jest.clearAllMocks());

  it('запускает batch POST /batches', async () => {
    mockApi.post.mockResolvedValueOnce({ data: MOCK_BATCH });

    const { result } = renderQueryHook(() => useStartBatch());

    result.current.mutate({
      script_id: 'scr-001',
      device_ids: ['dev-001', 'dev-002'],
      wave_size: 10,
      wave_delay_ms: 5000,
      name: 'Ночной фарм',
      priority: 5,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/batches', {
      script_id: 'scr-001',
      device_ids: ['dev-001', 'dev-002'],
      wave_size: 10,
      wave_delay_ms: 5000,
      name: 'Ночной фарм',
      priority: 5,
    });
    expect(result.current.data).toEqual(MOCK_BATCH);
  });
});

describe('useBatch', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает батч по ID', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_BATCH });

    const { result } = renderQueryHook(() => useBatch('batch-001'));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.total).toBe(50);
    expect(result.current.data?.succeeded).toBe(20);
  });

  it('не запрашивает при пустом batchId', async () => {
    renderQueryHook(() => useBatch(''));

    await new Promise((r) => setTimeout(r, 50));
    expect(mockApi.get).not.toHaveBeenCalled();
  });
});

describe('useCancelBatch', () => {
  beforeEach(() => jest.clearAllMocks());

  it('отменяет батч DELETE /batches/{id}', async () => {
    mockApi.delete.mockResolvedValueOnce({ data: null });

    const { result } = renderQueryHook(() => useCancelBatch());

    result.current.mutate('batch-001');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.delete).toHaveBeenCalledWith('/batches/batch-001');
  });
});
