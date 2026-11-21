import { fireEvent, render, screen, within } from '@testing-library/react';
import TaskEnginePage from '@/app/(dashboard)/tasks/page';
import { type BatchTarget } from '@/lib/hooks/useBatches';

const batchId = 'batch-100';
const mockUseTasks = jest.fn();
const mockSearchParams = jest.fn();
const mockUseBatch = jest.fn();
const mockUseBatchList = jest.fn();
const mockCancel = jest.fn();
const mockUseCapabilities = jest.fn(() => ({ can: () => true }));
jest.mock('next/navigation', () => ({
  useSearchParams: () => mockSearchParams(),
}));
jest.mock('@/lib/hooks/useTasks', () => ({ useTasks: (params: unknown) => mockUseTasks(params) }));
jest.mock('@/lib/hooks/useBatches', () => ({
  ...jest.requireActual('@/lib/hooks/useBatches'),
  useBatch: (id: string) => mockUseBatch(id),
  useBatchList: (page: number) => mockUseBatchList(page),
  useCancelBatch: () => ({ mutate: mockCancel, isPending: false }),
}));
jest.mock('@/src/features/access/Capabilities', () => ({
  useCapabilities: () => mockUseCapabilities(),
}));

const summary = {
  id: batchId, name: 'Nightly fleet', script_name: 'Scenario',
  status: 'running', total: 100, wave_count: 10, script_version_id: 'version-fixed', next_wave_index: 1,
  created_at: '2026-11-14T00:00:00Z', admission_state: 'pending',
};

beforeEach(() => {
  jest.clearAllMocks();
  mockSearchParams.mockReturnValue(new URLSearchParams({ batch_id: batchId }));
  mockUseBatchList.mockReturnValue({ data: { items: [summary], pages: 1 }, isPending: false });
  const targets: BatchTarget[] = Array.from({ length: 100 }, (_, i) => ({
    device_id: 'device-' + (i + 1), device_name: 'Android ' + (i + 1),
    wave_index: Math.floor(i / 10), state: i === 0 ? 'running' : i === 1 ? 'rejected' : 'pending_admission',
    task_id: i === 0 ? 'task-real' : null, admission_http_status: i === 1 ? 409 : null,
    cancel_requested_at: null, timeout_requested_at: null,
  }));
  mockUseBatch.mockReturnValue({
    data: { ...summary, targets, target_counts: { running: 1, rejected: 1, pending_admission: 98 } },
    isSuccess: true,
  });
});

it('opens the linked 100-target run without loading global tasks, filters later waves and links only persisted tasks', () => {
  render(<TaskEnginePage />);
  expect(mockUseBatch).toHaveBeenCalledWith(batchId);
  expect(mockUseTasks).not.toHaveBeenCalled();
  expect(screen.getByText('version-fixed')).toBeInTheDocument();
  expect(screen.getByText('Найдено 100 из 100 целей.')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Открыть задание task-real' })).toHaveAttribute('href', '/tasks/task-real');
  const rejection = screen.getByText('Отказ до создания задачи (HTTP 409)').closest('tr')!;
  expect(within(rejection).queryByRole('link')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Волна'), { target: { value: '9' } });
  expect(screen.getByText('Найдено 10 из 100 целей.')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Поиск цели'), { target: { value: 'Android 100' } });
  expect(screen.getByText('Найдено 1 из 100 целей.')).toBeInTheDocument();
  expect(screen.getByText('Android 100')).toBeInTheDocument();
});

it('opens the batch index and keeps historical child reads scoped', () => {
  mockSearchParams.mockReturnValue(new URLSearchParams({ view: 'batches' }));
  const view = render(<TaskEnginePage />);
  expect(screen.getByRole('link', { name: 'Nightly fleet' })).toHaveAttribute('href', '/tasks?batch_id=batch-100');
  expect(mockUseTasks).not.toHaveBeenCalled();
  mockSearchParams.mockReturnValue(new URLSearchParams({ batch_id: batchId }));
  mockUseBatch.mockReturnValue({ data: { ...summary, targets: null }, isSuccess: true });
  mockUseTasks.mockReturnValue({ data: { items: [], total: 0, pages: 0 } });
  view.rerender(<TaskEnginePage />);
  expect(mockUseTasks).toHaveBeenCalledWith({ batch_id: batchId, page: 1, per_page: 25 });
  expect(screen.getByText(/План волн и итог по всем целям/)).toBeInTheDocument();
});

it('requires confirmation before cancellation', () => {
  render(<TaskEnginePage />);
  fireEvent.click(screen.getByRole('button', { name: 'Остановить пакет' }));
  expect(mockCancel).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить остановку' }));
  expect(mockCancel).toHaveBeenCalledWith(batchId, expect.any(Object));
});
