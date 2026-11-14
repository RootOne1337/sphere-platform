/**
 * Тесты хуков групп — CRUD, перемещение устройств, теги.
 * Покрытие: useGroups, useCreateGroup, useUpdateGroup, useDeleteGroup, useChangeGroupMembership, useTags.
 */
import { waitFor } from '@testing-library/react';
import { renderQueryHook } from '../helpers';
import {
  useGroups,
  useCreateGroup,
  useUpdateGroup,
  useDeleteGroup,
  useChangeGroupMembership,
  useTags,
} from '@/lib/hooks/useGroups';
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

const MOCK_GROUP = {
  id: 'grp-001',
  name: 'Фарм-группа Alpha',
  description: 'Основная фарм-группа',
  color: '#22c55e',
  parent_group_id: null,
  org_id: 'org-001',
  total_devices: 10,
  online_devices: 8,
};

describe('useGroups', () => {
  beforeEach(() => jest.clearAllMocks());

  it('does not read or poll groups until the caller admits access', async () => {
    mockApi.get.mockResolvedValue({ data: [MOCK_GROUP] });
    let enabled = false;
    const view = renderQueryHook(() => useGroups(enabled));
    expect(mockApi.get).not.toHaveBeenCalled();
    enabled = true; view.rerender();
    await waitFor(() => expect(view.result.current.isSuccess).toBe(true));
    expect(mockApi.get).toHaveBeenCalledTimes(1);
    enabled = false; view.rerender();
    expect(view.result.current.fetchStatus).toBe('idle');
  });

  it('загружает список групп', async () => {
    mockApi.get.mockResolvedValueOnce({ data: [MOCK_GROUP] });

    const { result } = renderQueryHook(() => useGroups());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].name).toBe('Фарм-группа Alpha');
  });
});

describe('useCreateGroup', () => {
  beforeEach(() => jest.clearAllMocks());

  it('создаёт группу POST /groups', async () => {
    mockApi.post.mockResolvedValueOnce({ data: MOCK_GROUP });

    const { result } = renderQueryHook(() => useCreateGroup());

    result.current.mutate({ name: 'Фарм-группа Alpha', description: 'Основная', color: '#22c55e' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/groups', {
      name: 'Фарм-группа Alpha',
      description: 'Основная',
      color: '#22c55e',
    });
  });
});

describe('useUpdateGroup', () => {
  beforeEach(() => jest.clearAllMocks());

  it('обновляет группу PUT /groups/{id}', async () => {
    mockApi.put.mockResolvedValueOnce({ data: { ...MOCK_GROUP, name: 'Beta', color: '#3b82f6' } });

    const { result } = renderQueryHook(() => useUpdateGroup());

    result.current.mutate({ groupId: 'grp-001', name: 'Beta', color: '#3b82f6' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.put).toHaveBeenCalledWith('/groups/grp-001', {
      name: 'Beta',
      color: '#3b82f6',
    });
  });

  it('обновляет parent_group_id (вложенные группы)', async () => {
    mockApi.put.mockResolvedValueOnce({ data: { ...MOCK_GROUP, id: 'grp-002', parent_group_id: 'grp-001' } });

    const { result } = renderQueryHook(() => useUpdateGroup());

    result.current.mutate({ groupId: 'grp-002', parent_group_id: 'grp-001' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.put).toHaveBeenCalledWith('/groups/grp-002', {
      parent_group_id: 'grp-001',
    });
  });
});

describe('useDeleteGroup', () => {
  beforeEach(() => jest.clearAllMocks());

  it('удаляет группу DELETE /groups/{id}', async () => {
    mockApi.delete.mockResolvedValueOnce({ status: 204, data: null });

    const { result } = renderQueryHook(() => useDeleteGroup());

    result.current.mutate('grp-001');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.delete).toHaveBeenCalledWith('/groups/grp-001');
  });
});

describe('useChangeGroupMembership', () => {
  beforeEach(() => jest.clearAllMocks());

  it('returns the outcome for each requested device', async () => {
    const results = [
      { device_id: 'dev-001', outcome: 'changed' },
      { device_id: 'dev-002', outcome: 'unchanged' },
      { device_id: 'dev-003', outcome: 'device_not_found' },
    ];
    mockApi.post.mockResolvedValueOnce({ data: { group_id: 'grp-001', operation: 'add', results } });

    const { result } = renderQueryHook(() => useChangeGroupMembership());

    result.current.mutate({ groupId: 'grp-001', deviceIds: ['dev-001', 'dev-002', 'dev-003'], operation: 'add' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(results);
    expect(mockApi.post).toHaveBeenCalledWith('/groups/grp-001/devices/membership', {
      device_ids: ['dev-001', 'dev-002', 'dev-003'], operation: 'add',
    });
  });

  it.each([
    [['dev-001']],
    [['dev-001', 'dev-001']],
    [['dev-001', 'other']],
  ])('rejects an unconfirmed membership receipt (%j)', async (ids) => {
    const results = ids.map(device_id => ({ device_id, outcome: 'changed' }));
    mockApi.post.mockResolvedValueOnce({ data: { group_id: 'grp-001', operation: 'remove', results } });
    const { result } = renderQueryHook(() => useChangeGroupMembership());
    result.current.mutate({ groupId: 'grp-001', deviceIds: ['dev-001', 'dev-002'], operation: 'remove' });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useTags', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает список тегов', async () => {
    mockApi.get.mockResolvedValueOnce({ data: ['production', 'staging', 'test'] });

    const { result } = renderQueryHook(() => useTags());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(['production', 'staging', 'test']);
  });
});
