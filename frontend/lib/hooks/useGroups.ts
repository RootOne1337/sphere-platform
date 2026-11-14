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

function isGroup(value: unknown): value is Group {
  if (typeof value !== 'object' || value === null) return false;
  const group = value as Group;
  return typeof group.id === 'string' && !!group.id && typeof group.name === 'string' && !!group.name.trim()
    && (group.description === null || typeof group.description === 'string')
    && (group.color === null || (typeof group.color === 'string' && /^#[0-9a-f]{6}$/i.test(group.color)))
    && (group.parent_group_id === null || typeof group.parent_group_id === 'string')
    && typeof group.org_id === 'string' && Number.isSafeInteger(group.total_devices) && group.total_devices >= 0
    && Number.isSafeInteger(group.online_devices) && group.online_devices >= 0 && group.online_devices <= group.total_devices;
}

export function useGroups(enabled = true) {
  return useQuery<Group[]>({
    queryKey: ['groups'],
    enabled,
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/groups', { signal });
      if (!Array.isArray(data) || !data.every(isGroup)) throw new Error('Состав каталога групп не подтверждён сервером.');
      return data;
    },
    refetchInterval: 30_000,
  });
}

export function useCreateGroup() {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: async (body: { name: string; description?: string; color?: string; parent_group_id?: string }) => {
      const { data } = await api.post('/groups', body);
      if (!isGroup(data) || data.name !== body.name || (body.parent_group_id !== undefined && data.parent_group_id !== body.parent_group_id)) throw new Error('Результат создания группы не подтверждён сервером. Обновите каталог перед повторной командой.');
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['groups'] }),
  });
}

export function useDeleteGroup() {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: async (groupId: string) => {
      const response = await api.delete(`/groups/${groupId}`);
      if (response.status !== 204) throw new Error('Результат удаления группы не подтверждён сервером.');
      return response;
    },
    onSuccess: async () => {
      await Promise.all([qc.invalidateQueries({ queryKey: ['groups'] }), qc.invalidateQueries({ queryKey: ['devices'] })]);
    },
  });
}

/** Обновить группу (имя, описание, цвет, родительская группа). Бекенд: PUT /groups/{id} */
export function useUpdateGroup() {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: async ({ groupId, ...body }: {
      groupId: string;
      name?: string;
      description?: string;
      color?: string;
      parent_group_id?: string | null;
    }) => {
      const { data } = await api.put(`/groups/${groupId}`, body);
      if (!isGroup(data) || data.id !== groupId || Object.entries(body).some(([key, value]) => data[key as keyof Group] !== value)) {
        throw new Error('Результат изменения группы не подтверждён сервером. Обновите каталог перед повторной командой.');
      }
      return data;
    },
    onSuccess: async () => {
      await Promise.all([qc.invalidateQueries({ queryKey: ['groups'] }), qc.invalidateQueries({ queryKey: ['devices'] })]);
    },
  });
}

export type GroupMembershipOperation = 'add' | 'remove' | 'replace';

type GroupMembershipOutcome = 'changed' | 'unchanged' | 'device_not_found';
type GroupMembershipResult = { device_id: string; outcome: GroupMembershipOutcome };

export function useChangeGroupMembership() {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: async ({ groupId, deviceIds, operation }: {
      groupId: string; deviceIds: string[]; operation: GroupMembershipOperation;
    }): Promise<GroupMembershipResult[]> => {
      const { data } = await api.post(`/groups/${groupId}/devices/membership`, { device_ids: deviceIds, operation });
      const remaining = new Set(deviceIds);
      if (data?.group_id !== groupId || data.operation !== operation || !Array.isArray(data.results)
        || data.results.length !== remaining.size || !data.results.every((item: GroupMembershipResult | null) =>
          item && remaining.delete(item.device_id) && ['changed', 'unchanged', 'device_not_found'].includes(item.outcome))) {
        throw new Error('Результат изменения групп не подтверждён сервером.');
      }
      return data.results;
    },
    onSettled: async () => {
      await Promise.all([qc.invalidateQueries({ queryKey: ['groups'] }), qc.invalidateQueries({ queryKey: ['devices'] })]);
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
