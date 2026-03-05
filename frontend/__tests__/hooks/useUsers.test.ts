/**
 * Тесты хуков пользователей — список, создание, смена роли, деактивация.
 * Покрытие: useUsers, useCreateUser, useUpdateRole, useDeactivateUser.
 */
import { waitFor } from '@testing-library/react';
import { renderQueryHook } from '../helpers';
import {
  useUsers,
  useCreateUser,
  useUpdateRole,
  useDeactivateUser,
} from '@/lib/hooks/useUsers';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    patch: jest.fn(),
  },
}));

const mockApi = api as jest.Mocked<typeof api>;

const MOCK_USER = {
  id: 'user-001',
  org_id: 'org-001',
  email: 'admin@sphere.io',
  role: 'admin',
  is_active: true,
  mfa_enabled: false,
  last_login_at: '2026-03-04T08:00:00Z',
  created_at: '2025-12-01T00:00:00Z',
};

const MOCK_USERS_RESPONSE = {
  items: [MOCK_USER],
  total: 1,
  page: 1,
  per_page: 50,
  pages: 1,
};

describe('useUsers', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает список пользователей', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_USERS_RESPONSE });

    const { result } = renderQueryHook(() => useUsers());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.items[0].email).toBe('admin@sphere.io');
  });

  it('передаёт параметры пагинации', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_USERS_RESPONSE });

    renderQueryHook(() => useUsers(2, 10));

    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    expect(mockApi.get).toHaveBeenCalledWith('/users', {
      params: { page: 2, per_page: 10 },
    });
  });
});

describe('useCreateUser', () => {
  beforeEach(() => jest.clearAllMocks());

  it('создаёт пользователя POST /users', async () => {
    mockApi.post.mockResolvedValueOnce({ data: MOCK_USER });

    const { result } = renderQueryHook(() => useCreateUser());

    result.current.mutate({ email: 'new@sphere.io', password: 'SecureP@ss123!', role: 'operator' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/users', {
      email: 'new@sphere.io',
      password: 'SecureP@ss123!',
      role: 'operator',
    });
  });
});

describe('useUpdateRole', () => {
  beforeEach(() => jest.clearAllMocks());

  it('меняет роль пользователя PUT /users/{id}/role', async () => {
    mockApi.put.mockResolvedValueOnce({ data: { ...MOCK_USER, role: 'viewer' } });

    const { result } = renderQueryHook(() => useUpdateRole());

    result.current.mutate({ userId: 'user-001', role: 'viewer' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.put).toHaveBeenCalledWith('/users/user-001/role', { role: 'viewer' });
  });
});

describe('useDeactivateUser', () => {
  beforeEach(() => jest.clearAllMocks());

  it('деактивирует пользователя PATCH /users/{id}/deactivate', async () => {
    mockApi.patch.mockResolvedValueOnce({ data: null });

    const { result } = renderQueryHook(() => useDeactivateUser());

    result.current.mutate('user-001');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.patch).toHaveBeenCalledWith('/users/user-001/deactivate');
  });
});
