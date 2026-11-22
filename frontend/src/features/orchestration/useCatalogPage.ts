'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { parseCatalogPage } from './listPayload';

export type CatalogKind = 'pipelines' | 'pipeline-runs' | 'schedules';
export type CatalogFilter = Record<string, string | boolean | undefined>;
export const CATALOG_PER_PAGE = 100;

export function useCatalogPage<T extends { id: string }>(kind: CatalogKind, page: number, filters: CatalogFilter = {}, options?: { enabled?: boolean; polling?: boolean }) {
  const params = { page, per_page: CATALOG_PER_PAGE, ...filters };
  return useQuery({
    queryKey: [kind, params],
    queryFn: async ({ signal }) => {
      const { data } = await api.get(kind === 'pipeline-runs' ? '/pipelines/runs' : `/${kind}`, { params, signal });
      return parseCatalogPage<T>(data, kind, page, CATALOG_PER_PAGE);
    },
    enabled: options?.enabled ?? true,
    refetchInterval: options?.polling === false ? false : kind === 'pipeline-runs' ? 5000 : 8000,
    refetchIntervalInBackground: false,
    staleTime: 5000,
  });
}
