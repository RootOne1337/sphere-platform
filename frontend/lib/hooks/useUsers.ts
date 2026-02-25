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

export function useUsers(page = 1, perPage = 50) {
  return useQuery<UsersResponse>({
    queryKey: ['users', page, perPage],
    queryFn: async () => {
      const { data } = await api.get('/users', { params: { page, per_page: perPage } });
      return data;
    },
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { email: string; password: string; role: string }) => {
      const { data } = await api.post('/users', body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
}

export function useUpdateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ userId, role }: { userId: string; role: string }) => {
      const { data } = await api.put(`/users/${userId}/role`, { role });
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
}

export function useDeactivateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string) => {
      await api.patch(`/users/${userId}/deactivate`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  });
}
