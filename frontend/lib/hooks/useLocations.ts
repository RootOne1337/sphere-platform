import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface Location {
  id: string;
  name: string;
  description: string | null;
  color: string | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  parent_location_id: string | null;
  org_id: string;
  total_devices: number;
  online_devices: number;
}

export function useLocations() {
  return useQuery<Location[]>({
    queryKey: ['locations'],
    queryFn: async () => {
      const { data } = await api.get('/locations');
      return data;
    },
  });
}

export function useCreateLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      name: string;
      description?: string;
      color?: string;
      address?: string;
      latitude?: number;
      longitude?: number;
      parent_location_id?: string;
    }) => {
      const { data } = await api.post('/locations', body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['locations'] }),
  });
}

export function useUpdateLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: { id: string; name?: string; description?: string; color?: string; address?: string }) => {
      const { data } = await api.put(`/locations/${id}`, body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['locations'] }),
  });
}

export function useDeleteLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (locationId: string) => api.delete(`/locations/${locationId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['locations'] }),
  });
}

export function useAssignDevicesToLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ locationId, deviceIds }: { locationId: string; deviceIds: string[] }) => {
      const { data } = await api.post(`/locations/${locationId}/devices`, { device_ids: deviceIds });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['locations'] });
      qc.invalidateQueries({ queryKey: ['devices'] });
    },
  });
}

export function useRemoveDevicesFromLocation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ locationId, deviceIds }: { locationId: string; deviceIds: string[] }) => {
      const { data } = await api.delete(`/locations/${locationId}/devices`, { data: { device_ids: deviceIds } });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['locations'] });
      qc.invalidateQueries({ queryKey: ['devices'] });
    },
  });
}
