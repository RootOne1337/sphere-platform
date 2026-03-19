/**
 * Тесты хуков локаций — CRUD, привязка/отвязка устройств.
 * Покрытие: useLocations, useCreateLocation, useUpdateLocation, useDeleteLocation,
 * useAssignDevicesToLocation, useRemoveDevicesFromLocation.
 */
import { waitFor } from '@testing-library/react';
import { renderQueryHook } from '../helpers';
import {
  useLocations,
  useCreateLocation,
  useUpdateLocation,
  useDeleteLocation,
  useAssignDevicesToLocation,
  useRemoveDevicesFromLocation,
} from '@/lib/hooks/useLocations';
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

const MOCK_LOCATION = {
  id: 'loc-001',
  name: 'Серверная М-01',
  description: 'Основная серверная',
  color: '#f59e0b',
  address: 'Москва, ул. Тверская, 1',
  latitude: 55.7558,
  longitude: 37.6173,
  parent_location_id: null,
  org_id: 'org-001',
  total_devices: 20,
  online_devices: 18,
};

describe('useLocations', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает список локаций', async () => {
    mockApi.get.mockResolvedValueOnce({ data: [MOCK_LOCATION] });

    const { result } = renderQueryHook(() => useLocations());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].latitude).toBe(55.7558);
  });
});

describe('useCreateLocation', () => {
  beforeEach(() => jest.clearAllMocks());

  it('создаёт локацию с координатами', async () => {
    mockApi.post.mockResolvedValueOnce({ data: MOCK_LOCATION });

    const { result } = renderQueryHook(() => useCreateLocation());

    result.current.mutate({
      name: 'Серверная М-01',
      latitude: 55.7558,
      longitude: 37.6173,
      address: 'Москва, ул. Тверская, 1',
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/locations', expect.objectContaining({
      name: 'Серверная М-01',
      latitude: 55.7558,
    }));
  });
});

describe('useUpdateLocation', () => {
  beforeEach(() => jest.clearAllMocks());

  it('обновляет локацию PUT /locations/{id}', async () => {
    mockApi.put.mockResolvedValueOnce({ data: { ...MOCK_LOCATION, name: 'Обновлённая' } });

    const { result } = renderQueryHook(() => useUpdateLocation());

    result.current.mutate({ id: 'loc-001', name: 'Обновлённая' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.put).toHaveBeenCalledWith('/locations/loc-001', { name: 'Обновлённая' });
  });
});

describe('useDeleteLocation', () => {
  beforeEach(() => jest.clearAllMocks());

  it('удаляет локацию DELETE /locations/{id}', async () => {
    mockApi.delete.mockResolvedValueOnce({ data: null });

    const { result } = renderQueryHook(() => useDeleteLocation());

    result.current.mutate('loc-001');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.delete).toHaveBeenCalledWith('/locations/loc-001');
  });
});

describe('useAssignDevicesToLocation', () => {
  beforeEach(() => jest.clearAllMocks());

  it('привязывает устройства к локации', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { assigned: 2 } });

    const { result } = renderQueryHook(() => useAssignDevicesToLocation());

    result.current.mutate({ locationId: 'loc-001', deviceIds: ['dev-001', 'dev-002'] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/locations/loc-001/devices', {
      device_ids: ['dev-001', 'dev-002'],
    });
  });
});

describe('useRemoveDevicesFromLocation', () => {
  beforeEach(() => jest.clearAllMocks());

  it('отвязывает устройства от локации', async () => {
    mockApi.delete.mockResolvedValueOnce({ data: { removed: 1 } });

    const { result } = renderQueryHook(() => useRemoveDevicesFromLocation());

    result.current.mutate({ locationId: 'loc-001', deviceIds: ['dev-001'] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.delete).toHaveBeenCalledWith('/locations/loc-001/devices', {
      data: { device_ids: ['dev-001'] },
    });
  });
});
