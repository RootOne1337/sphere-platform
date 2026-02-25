import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface Group {
  id: string;
  name: string;
  description: string | null;
  color: string | null;
  parent_group_id: string | null;
  org_id: string;
  total_devices: number;
  online_devices: number;
}

export function useGroups() {
  return useQuery<Group[]>({
    queryKey: ['groups'],
    queryFn: async () => {
      const { data } = await api.get('/groups');
      return data;
    },
  });
}

export function useCreateGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { name: string; description?: string; color?: string }) => {
      const { data } = await api.post('/groups', body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['groups'] }),
  });
}

export function useDeleteGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (groupId: string) => api.delete(`/groups/${groupId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['groups'] }),
  });
}

export function useMoveDevices() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ groupId, deviceIds }: { groupId: string; deviceIds: string[] }) => {
      const { data } = await api.post(`/groups/${groupId}/devices/move`, { device_ids: deviceIds });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['groups'] });
      qc.invalidateQueries({ queryKey: ['devices'] });
    },
  });
}

export function useTags() {
  return useQuery<string[]>({
    queryKey: ['tags'],
    queryFn: async () => {
      const { data } = await api.get('/groups/tags');
      return data;
    },
  });
}
