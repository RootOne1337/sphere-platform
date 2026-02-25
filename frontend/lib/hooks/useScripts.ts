import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface Script {
  id: string;
  name: string;
  description: string | null;
  is_archived: boolean;
  node_count: number;
  created_at: string;
  updated_at: string;
}

export function useScripts() {
  return useQuery<Script[]>({
    queryKey: ['scripts'],
    queryFn: async () => {
      const { data } = await api.get('/scripts');
      return Array.isArray(data) ? data : (data.items ?? []);
    },
    staleTime: 30_000,
  });
}
