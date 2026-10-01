import { act, renderHook, waitFor } from '@testing-library/react';
import { api } from '@/lib/api';
import { useRetryTask } from '@/lib/hooks/useTasks';
import { createTestQueryClient, createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
beforeEach(() => jest.clearAllMocks());

it('lets the server resolve the source context by task ID rather than posting a stale copy', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { id: 'new', status: 'queued' } } as never);
  const { result } = renderHook(() => useRetryTask(), { wrapper: createWrapper(createTestQueryClient()) });
  await act(async () => { await result.current.mutateAsync('original' as never); });
  expect(api.post).toHaveBeenCalledWith('/tasks/original/rerun');
  await waitFor(() => expect(result.current.data).toEqual({ id: 'new', status: 'queued' }));
});

it('never automatically replays an uncertain create response', async () => {
  jest.mocked(api.post).mockRejectedValue(new Error('response lost'));
  const client = createTestQueryClient();
  client.setMutationDefaults(['tasks'], { retry: 3 });
  const { result } = renderHook(() => useRetryTask(), { wrapper: createWrapper(client) });
  await act(async () => { result.current.mutate('original' as never); });
  await waitFor(() => expect(result.current.isError).toBe(true));
  expect(api.post).toHaveBeenCalledTimes(1);
});
