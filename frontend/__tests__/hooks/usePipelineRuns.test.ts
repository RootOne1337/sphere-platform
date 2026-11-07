import { waitFor } from '@testing-library/react';
import { renderQueryHook } from '../helpers';
import { useActivePipelineRuns } from '@/lib/hooks/usePipelineRuns';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));

it('requests active pipeline runs from the server before limiting the preview', async () => {
  jest.mocked(api.get).mockResolvedValueOnce({ data: { items: [{ id:'old-waiting', status:'waiting' }], total:12 } });
  const {result} = renderQueryHook(() => useActivePipelineRuns());
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(api.get).toHaveBeenCalledWith('/pipelines/runs', {params:{active_only:true,per_page:10}});
  expect(result.current.data?.total).toBe(12);
});
