import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface UserInfo {
  id: string;
  org_id: string;
  email: string;
  role: string;
  is_active: boolean;
  mfa_enabled: boolean;
  last_login_at: string | null;
  created_at: string;
}

interface UsersResponse {
  items: UserInfo[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export function useUsers(page = 1, perPage = 50, options: { enabled?: boolean; scope?: string } = {}) {
  return useQuery<UsersResponse>({
    queryKey: ['users', options.scope, page, perPage],
    enabled: options.enabled,
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/users', { params: { page, per_page: perPage }, signal });
      if (!data || !Array.isArray(data.items) || !data.items.every(isUserInfo)
        || !Number.isInteger(data.total) || data.total < 0 || !Number.isInteger(data.pages) || data.pages < 0
        || data.page !== page || data.per_page !== perPage) throw new Error('Invalid users catalog');
      return data;
    },
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

function isUserInfo(value: unknown): value is UserInfo {
  if (!value || typeof value !== 'object') return false;
  const user = value as Partial<UserInfo>;
  return typeof user.id === 'string' && Boolean(user.id) && typeof user.org_id === 'string' && Boolean(user.org_id)
    && typeof user.email === 'string' && Boolean(user.email) && typeof user.role === 'string' && Boolean(user.role)
    && typeof user.is_active === 'boolean' && typeof user.mfa_enabled === 'boolean' && typeof user.created_at === 'string'
    && (user.last_login_at === null || typeof user.last_login_at === 'string');
}

export function useCreateUser(orgId?: string) {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: async (body: { email: string; password: string; role: string }) => {
      const { data } = await api.post('/users', body);
      if (!isUserInfo(data) || (orgId && data.org_id !== orgId) || data.email.toLowerCase() !== body.email.toLowerCase() || data.role !== body.role || !data.is_active) {
        throw new Error('User creation not confirmed');
      }
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
}

export function useUpdateRole() {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: async ({ userId, role, orgId }: { userId: string; role: string; orgId?: string }) => {
      const { data } = await api.put(`/users/${userId}/role`, { role });
      if (!isUserInfo(data) || data.id !== userId || (orgId && data.org_id !== orgId) || data.role !== role) throw new Error('User role change not confirmed');
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
}

export function useDeactivateUser() {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: async (userId: string) => {
      const response = await api.patch(`/users/${userId}/deactivate`);
      if (response.status !== 204) throw new Error('User deactivation not confirmed');
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
}
