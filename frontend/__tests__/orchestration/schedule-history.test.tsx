import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ScheduleExecutionHistoryDialog } from '@/components/orchestration/ScheduleExecutionHistoryDialog';
import OrchestrationPage from '@/app/(dashboard)/orchestration/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [] } }) }));
jest.mock('@/components/sphere/DeviceSelector', () => ({ DeviceSelector: () => null }));
const schedule = { id: 'schedule-1', name: 'Scheduled canary' };
const execution = (id: string, scheduleId = 'schedule-1') => ({ id, schedule_id: scheduleId, status: 'skipped',
  fire_time: '2026-10-01T10:30:00Z', actual_time: '2026-10-01T10:30:01Z', devices_targeted: 2,
  tasks_created: 0, tasks_succeeded: 0, tasks_failed: 0, skip_reason: 'no online targets', batch_id: null, pipeline_batch_id: null });
const envelope = (page = 1, items = [execution(`execution-${page}`)], total = 51) => ({ data: { items, total, page, per_page: 50, pages: Math.ceil(total / 50) } });
beforeEach(() => jest.resetAllMocks());

it('opens history from the real schedule row and reports times, counters, skip reason and IDs without firing the schedule', async () => {
  jest.mocked(api.get).mockImplementation(async (url) => url.includes('/executions') ? envelope() as never : { data: { items: url.startsWith('/schedules?') ? [{ ...schedule, target_type: 'pipeline', is_active: true, total_runs: 1, conflict_policy: 'skip' }] : [], total: 1 } } as never);
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  fireEvent.click(await screen.findByRole('button', { name: 'История срабатываний: Scheduled canary' }));
  const dialog = screen.getByRole('dialog');
  expect(await within(dialog).findByText('no online targets')).toBeInTheDocument();
  expect(within(dialog).getByText('execution-1')).toBeInTheDocument();
  expect(within(dialog).getByText('2026-10-01 10:30:00.000 UTC')).toBeInTheDocument();
  expect(within(dialog).getByText('0 / 0')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/schedules/schedule-1/executions', { params: { page: 1, per_page: 50 }, signal: expect.any(AbortSignal) });
  expect(api.post).not.toHaveBeenCalled();
});

it('pages past the first 50 execution records and resets paging when another schedule is selected', async () => {
  jest.mocked(api.get).mockImplementation(async (url, config) => {
    const page = (config?.params as { page?: number })?.page ?? 1;
    return envelope(page, [execution(`execution-${page}-${url}`, url.includes('schedule-2') ? 'schedule-2' : 'schedule-1')]) as never;
  });
  const view = render(<ScheduleExecutionHistoryDialog schedule={schedule} onClose={jest.fn()} />, { wrapper: createWrapper() });
  await screen.findByText('Страница 1 из 2 · всего 51');
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: срабатывания расписания' }));
  await screen.findByText('Страница 2 из 2 · всего 51');
  expect(api.get).toHaveBeenLastCalledWith('/schedules/schedule-1/executions', { params: { page: 2, per_page: 50 }, signal: expect.any(AbortSignal) });
  view.rerender(<ScheduleExecutionHistoryDialog schedule={{ id: 'schedule-2', name: 'Other' }} onClose={jest.fn()} />);
  await screen.findByText('Страница 1 из 2 · всего 51');
  expect(api.get).toHaveBeenLastCalledWith('/schedules/schedule-2/executions', { params: { page: 1, per_page: 50 }, signal: expect.any(AbortSignal) });
});

it('does not label a failed history read as an empty history and supports explicit retry', async () => {
  jest.mocked(api.get).mockRejectedValueOnce(new Error('permission denied')).mockResolvedValueOnce(envelope(1, [], 0) as never);
  render(<ScheduleExecutionHistoryDialog schedule={schedule} onClose={jest.fn()} />, { wrapper: createWrapper() });
  expect(await screen.findByRole('alert')).toHaveTextContent('permission denied');
  expect(screen.queryByText('Срабатываний пока нет.')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить историю' }));
  expect(await screen.findByText('Срабатываний пока нет.')).toBeInTheDocument();
});

it('hides unconfirmed cached history after a failed refresh', async () => {
  jest.mocked(api.get).mockResolvedValueOnce(envelope() as never).mockRejectedValueOnce(new Error('offline'));
  render(<ScheduleExecutionHistoryDialog schedule={schedule} onClose={jest.fn()} />, { wrapper: createWrapper() });
  await screen.findByText('execution-1');
  fireEvent.click(screen.getByRole('button', { name: 'Обновить историю' }));
  await screen.findByRole('alert');
  expect(screen.queryByText('execution-1')).not.toBeInTheDocument();
  expect(screen.queryByText('Страница 1 из 2 · всего 51')).not.toBeInTheDocument();
});

it('rejects histories containing another schedule rather than displaying foreign evidence', async () => {
  jest.mocked(api.get).mockResolvedValue(envelope(1, [execution('foreign', 'schedule-2')]) as never);
  render(<ScheduleExecutionHistoryDialog schedule={schedule} onClose={jest.fn()} />, { wrapper: createWrapper() });
  expect(await screen.findByRole('alert')).toHaveTextContent('другого расписания');
  expect(screen.queryByText('foreign')).not.toBeInTheDocument();
});

it('cancels a closed history read and ignores its late response after opening another schedule', async () => {
  let resolve!: (value: ReturnType<typeof envelope>) => void;
  jest.mocked(api.get).mockReturnValueOnce(new Promise(r => { resolve = r; }) as never).mockResolvedValueOnce(envelope(1, [execution('second-owner', 'schedule-2')]) as never);
  const view = render(<ScheduleExecutionHistoryDialog schedule={schedule} onClose={jest.fn()} />, { wrapper: createWrapper() });
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
  const signal = jest.mocked(api.get).mock.calls[0][1]?.signal;
  view.rerender(<ScheduleExecutionHistoryDialog schedule={null} onClose={jest.fn()} />);
  expect(signal?.aborted).toBe(true);
  view.rerender(<ScheduleExecutionHistoryDialog schedule={{ id: 'schedule-2', name: 'Other' }} onClose={jest.fn()} />);
  await screen.findByText('second-owner');
  await act(async () => resolve(envelope(1, [execution('late-first-owner')])));
  expect(screen.queryByText('late-first-owner')).not.toBeInTheDocument();
});
