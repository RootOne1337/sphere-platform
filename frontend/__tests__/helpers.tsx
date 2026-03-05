/**
 * Вспомогательные утилиты для тестирования React Query хуков и компонентов.
 */
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, type RenderHookOptions } from '@testing-library/react';

/** Создаёт изолированный QueryClient для теста (retry=0, без кэша) */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

/** Обёртка-провайдер с QueryClient для renderHook */
export function createWrapper(queryClient?: QueryClient) {
  const qc = queryClient ?? createTestQueryClient();
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: qc }, children);
  };
}

/** Короткий хелпер renderHook с QueryClient */
export function renderQueryHook<TResult>(
  hook: () => TResult,
  options?: Omit<RenderHookOptions<unknown>, 'wrapper'> & { queryClient?: QueryClient },
) {
  const { queryClient, ...rest } = options ?? {};
  return renderHook(hook, {
    wrapper: createWrapper(queryClient),
    ...rest,
  });
}
