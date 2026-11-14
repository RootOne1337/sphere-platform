import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ScheduleExecutionHistoryDialog } from '@/components/orchestration/ScheduleExecutionHistoryDialog';
import OrchestrationPage from '@/app/(dashboard)/orchestration/page';
import { api } from '@/lib/api';
import { createTestQueryClient, createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [] } }) }));
jest.mock('@/components/sphere/DeviceSelector', () => ({ DeviceSelector: () => null }));
const schedule = { id: 'schedule-1', name: 'Scheduled canary', updated_at: '2026-10-20T13:00:00.123456Z' };
const execution = (id: string, scheduleId = 'schedule-1') => ({ id, schedule_id: scheduleId, status: 'skipped',
  fire_time: '2026-10-01T10:30:00Z', actual_time: '2026-10-01T10:30:01Z', devices_targeted: 2,
  tasks_created: 0, tasks_succeeded: 0, tasks_failed: 0, skip_reason: 'no online targets', batch_id: null, pipeline_batch_id: null });
const envelope = (page = 1, items = [execution(`execution-${page}`)], total = 51) => ({ data: { items, total, page, per_page: 50, pages: Math.ceil(total / 50) } });
beforeEach(() => {
  jest.resetAllMocks();
  sessionStorage.clear();
});

it('opens history from the real schedule row and reports times, counters, skip reason and IDs without firing the schedule', async () => {
  jest.mocked(api.get).mockImplementation(async (url) => url.includes('/executions') ? envelope() as never : { data: { items: url === '/schedules' ? [{ ...schedule, target_type: 'pipeline', is_active: true, total_runs: 1, conflict_policy: 'skip' }] : [], total: url === '/schedules' ? 1 : 0, page: 1, per_page: 100, pages: url === '/schedules' ? 1 : 0 } } as never);
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

it('shows a full UTC next-fire date, protects disabled rows and labels fire-now as accepted', async () => {
  const runAt = '2026-10-22T23:30:00-04:00';
  const active = { ...schedule, target_type: 'pipeline', is_active: true, total_runs: 1, conflict_policy: 'skip', next_fire_at: runAt };
  jest.mocked(api.get).mockImplementation(async url => {
    const items = url === '/schedules' ? [active, { ...active, id: 'off', name: 'Inactive', is_active: false }] : [];
    return { data: { items, total: items.length, page: 1, per_page: 100, pages: items.length ? 1 : 0 } } as never;
  });
  jest.mocked(api.post).mockResolvedValue({ data: { ...active, requested_fire_at: runAt, request_replayed: false } });
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  expect(await screen.findByText(/23 окт. 2026 г., 03:30:00 UTC/)).toHaveAttribute('datetime', runAt);
  expect(screen.getByRole('button', { name: 'Запросить запуск расписания Inactive' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Запросить запуск расписания Scheduled canary' }));
  expect(await screen.findByText('Запрос принят планировщиком. Откройте историю срабатываний для проверки результата.')).toBeInTheDocument();
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith('/schedules/schedule-1/fire-now', undefined, {
    headers: { 'Idempotency-Key': expect.stringMatching(/^[0-9a-f-]{36}$/) },
    params: { expected_updated_at: schedule.updated_at },
  });
});

it('shows the next cron slot in UTC and in the configured zone with its offset', async () => {
  const active = { ...schedule, target_type: 'pipeline', cron_expression: '30 1 * * *', timezone: 'America/New_York', is_active: true, next_fire_at: '2026-11-01T05:30:00Z' };
  jest.mocked(api.get).mockImplementation(async url => {
    const items = url === '/schedules' ? [active] : [];
    return { data: { items, total: items.length, page: 1, per_page: 100, pages: items.length ? 1 : 0 } } as never;
  });
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  expect(await screen.findByText(/05:30:00 UTC/)).toHaveAttribute('datetime', active.next_fire_at);
  expect(screen.getByText(/01:30:00 GMT-4.*America\/New_York/)).toBeInTheDocument();
});

it('reuses the same key after an unconfirmed response and a remount', async () => {
  const active = { ...schedule, target_type: 'pipeline', is_active: true, total_runs: 1, conflict_policy: 'skip' };
  jest.mocked(api.get).mockImplementation(async url => {
    const items = url === '/schedules' ? [active] : [];
    return { data: { items, total: items.length, page: 1, per_page: 100, pages: items.length ? 1 : 0 } } as never;
  });
  jest.mocked(api.post).mockRejectedValueOnce(new Error('Результат команды не подтверждён'))
    .mockResolvedValueOnce({ data: { id: schedule.id, requested_fire_at: '2026-10-01T10:30:00Z', request_replayed: true } });
  const first = render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  fireEvent.click(await screen.findByRole('button', { name: 'Запросить запуск расписания Scheduled canary' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Результат команды не подтверждён');
  first.unmount();
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  fireEvent.click(await screen.findByRole('button', { name: 'Запросить запуск расписания Scheduled canary' }));
  await screen.findByText('Запрос принят планировщиком. Откройте историю срабатываний для проверки результата.');
  expect(api.post).toHaveBeenCalledTimes(2);
  expect(jest.mocked(api.post).mock.calls[0][2]?.headers)
    .toEqual(jest.mocked(api.post).mock.calls[1][2]?.headers);
});

it('preserves a newer unconfirmed key when an earlier receipt arrives after remount', async () => {
  const active = { ...schedule, target_type: 'pipeline', is_active: true, total_runs: 1, conflict_policy: 'skip' };
  jest.mocked(api.get).mockImplementation(async url => {
    const items = url === '/schedules' ? [active] : [];
    return { data: { items, total: items.length, page: 1, per_page: 100, pages: items.length ? 1 : 0 } } as never;
  });
  const receipt = { data: { id: schedule.id, requested_fire_at: '2026-10-01T10:30:00Z', request_replayed: false } };
  let finishOriginal!: (value: typeof receipt) => void;
  jest.mocked(api.post)
    .mockImplementationOnce(() => new Promise(resolve => { finishOriginal = resolve; }))
    .mockResolvedValueOnce({ data: { ...receipt.data, request_replayed: true } })
    .mockRejectedValueOnce(new Error('Ответ на новый запрос потерян'))
    .mockResolvedValueOnce({ data: { ...receipt.data, request_replayed: true } });
  const requestFire = async () => {
    fireEvent.click(await screen.findByText('Schedules'));
    fireEvent.click(await screen.findByRole('button', { name: 'Запросить запуск расписания Scheduled canary' }));
  };
  const firstClient = createTestQueryClient();
  const first = render(<OrchestrationPage />, { wrapper: createWrapper(firstClient) });
  await requestFire();
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  first.unmount();

  const secondClient = createTestQueryClient();
  const second = render(<OrchestrationPage />, { wrapper: createWrapper(secondClient) });
  await requestFire();
  await waitFor(() => expect(secondClient.getMutationCache().getAll()[0]?.state.status).toBe('success'));
  fireEvent.click(screen.getByRole('button', { name: 'Запросить запуск расписания Scheduled canary' }));
  await screen.findByRole('alert');
  const [, firstReplay, newerRequest] = jest.mocked(api.post).mock.calls;
  expect(firstReplay[2]?.headers).toEqual(jest.mocked(api.post).mock.calls[0][2]?.headers);
  expect(newerRequest[2]?.headers).not.toEqual(firstReplay[2]?.headers);

  await act(async () => finishOriginal(receipt));
  await waitFor(() => expect(firstClient.getMutationCache().getAll()[0]?.state.status).toBe('success'));
  second.unmount();
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  await requestFire();
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(4));
  expect(jest.mocked(api.post).mock.calls[3][2]?.headers).toEqual(newerRequest[2]?.headers);
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

test.each([
  ['partial', 'Частичный результат', 1, 1],
  ['failed', 'Нет успешных результатов', 0, 2],
])('shows the server terminal outcome %s with its actual task counts', async (status, label, succeeded, failed) => {
  jest.mocked(api.get).mockResolvedValue(envelope(1, [{ ...execution('terminal'), status, tasks_created: 2, tasks_succeeded: succeeded, tasks_failed: failed }]) as never);
  render(<ScheduleExecutionHistoryDialog schedule={schedule} onClose={jest.fn()} />, { wrapper: createWrapper() });
  expect(await screen.findByText(label)).toBeInTheDocument();
  expect(screen.getByText(`${succeeded} / ${failed}`)).toBeInTheDocument();
  expect(screen.queryByText('Завершено')).not.toBeInTheDocument();
});
