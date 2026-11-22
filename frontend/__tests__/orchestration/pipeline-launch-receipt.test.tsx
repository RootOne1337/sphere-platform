import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import OrchestrationPage from '@/app/(dashboard)/orchestration/page';
import { api } from '@/lib/api';
import { toast } from 'sonner';
import { createWrapper } from '../helpers';

let mockSearch = '';
jest.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(mockSearch) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [] } }) }));
jest.mock('@/components/sphere/DeviceSelector', () => ({ DeviceSelector: ({ onChange }: { onChange: (ids: string[]) => void }) => (
  <><button type="button" onClick={() => onChange(['device-a'])}>Одна цель</button>
  <button type="button" onClick={() => onChange(['device-a', 'device-b'])}>Две цели</button></>
) }));
jest.mock('@/components/orchestration/PipelineResumeControl', () => ({ PipelineResumeControl: () => null }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

const pipeline = { id: 'pipeline-a', name: 'Pipeline A', description: null, steps: [], tags: [], version: 7,
  is_active: true, updated_at: '2026-11-14T11:00:00.235001Z' };

beforeEach(() => {
  jest.resetAllMocks();
  mockSearch = '';
  jest.mocked(api.get).mockImplementation(async url => ({ data: {
    items: url === '/pipelines' ? [pipeline] : [], page: 1, per_page: 100, total: url === '/pipelines' ? 1 : 0,
    pages: url === '/pipelines' ? 1 : 0,
  } }));
});

async function open() {
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByTitle('Запустить'));
}

it.each([
  { count: 1, target: 'Одна цель', path: 'run', kind: 'Запуск', key: 'run_id', targetBody: { device_id: 'device-a' } },
  { count: 2, target: 'Две цели', path: 'run-batch', kind: 'Пакет', key: 'batch_id', targetBody: { device_ids: ['device-a', 'device-b'] } },
])('pins the preview for $path and links to its confirmed receipt', async ({ count, target, path, kind, key, targetBody }) => {
  jest.mocked(api.post).mockResolvedValue({ data: {
    id: 'receipt-a', pipeline_id: pipeline.id, pipeline_version: pipeline.version,
    ...(count === 1 ? { device_id: 'device-a' } : { total: count }),
  } });
  await open();
  fireEvent.click(screen.getByText(target));
  fireEvent.click(screen.getByRole('button', { name: `Запустить (${count})` }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/pipelines/pipeline-a/${path}`, {
    ...targetBody, expected_version: 7, expected_updated_at: pipeline.updated_at, input_params: {},
  }));
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith(`${kind} принят`, { description: expect.anything() }));
  const receipt = render(jest.mocked(toast.success).mock.calls[0][1]!.description as React.ReactElement);
  expect(receipt.getByText('Версия 7 · receipt-a')).toBeInTheDocument();
  expect(receipt.getByRole('link', { name: 'Открыть результаты' })).toHaveAttribute('href', `/orchestration?${key}=receipt-a`);
});

it('blocks a repeat on a stale preview and leaves the dialog open', async () => {
  jest.mocked(api.post).mockRejectedValue({ response: { status: 409 } });
  await open();
  fireEvent.click(screen.getByText('Две цели'));
  const submit = screen.getByRole('button', { name: 'Запустить (2)' });
  fireEvent.click(submit);
  expect(await screen.findByRole('alert')).toHaveTextContent('Конвейер изменился или редактируется');
  expect(submit).toBeDisabled();
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(toast.success).not.toHaveBeenCalled();
});

it.each(['run_id', 'batch_id'])('reloads the receipt using exact %s filter', async key => {
  mockSearch = `${key}=receipt-a`;
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  expect(await screen.findByText('receipt-a')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/pipelines/runs', {
    params: { page: 1, per_page: 100, [key]: 'receipt-a' }, signal: expect.any(AbortSignal),
  });
});
