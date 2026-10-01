import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import OrchestrationPage from '@/app/(dashboard)/orchestration/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [] } }) }));
jest.mock('@/components/sphere/DeviceSelector', () => ({ DeviceSelector: ({ onChange }: { onChange: (ids: string[]) => void }) => <button onClick={() => onChange(['device-1'])}>Выбрать тестовую цель</button> }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
const schedule = { id: 'schedule-1', name: 'One shot canary', description: null, cron_expression: null, interval_seconds: null,
  one_shot_at: '2026-10-20T13:45:26.123456+05:00', timezone: 'Asia/Yekaterinburg', target_type: 'pipeline', pipeline_id: 'pipeline-1',
  script_id: null, conflict_policy: 'skip', is_active: true, device_ids: [], total_runs: 0, next_fire_at: null, last_fired_at: null };
beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(api.get).mockImplementation(async (url) => ({ data: { items: url.startsWith('/schedules?') ? [schedule] : url === '/pipelines?per_page=100' ? [{ id: 'pipeline-1', name: 'Canary', steps: [], version: 1, tags: [] }] : [], total: 1 } }) as never);
  jest.mocked(api.patch).mockResolvedValue({ data: schedule });
  jest.mocked(api.post).mockResolvedValue({ data: schedule });
});

async function openSchedule() {
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  await screen.findByText(schedule.name);
  fireEvent.click(screen.getByTitle('Редактировать'));
  return screen.getByRole('dialog');
}

it('edits an offset timestamp in explicit UTC and preserves the original instant and precision when unchanged', async () => {
  const dialog = await openSchedule();
  const input = within(dialog).getByLabelText('Дата и время запуска (UTC)') as HTMLInputElement;
  expect(input.value).toBe('2026-10-20T08:45:26.123');
  expect(within(dialog).getByText(/Часовой пояс расписания применяется к CRON/)).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить изменения' }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/schedules/schedule-1', expect.objectContaining({ one_shot_at: schedule.one_shot_at })));
});

it('sends a changed UTC wall time as an aware instant instead of appending malformed seconds', async () => {
  const dialog = await openSchedule();
  fireEvent.change(within(dialog).getByLabelText('Дата и время запуска (UTC)'), { target: { value: '2026-10-21T09:10:12.345' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить изменения' }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/schedules/schedule-1', expect.objectContaining({ one_shot_at: '2026-10-21T09:10:12.345Z' })));
});

it('creates one-shot schedules with the same UTC contract and does not submit an empty datetime', async () => {
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  fireEvent.click(await screen.findByRole('button', { name: 'Новое расписание' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Выбрать тестовую цель' }));
  fireEvent.change(within(dialog).getByPlaceholderText('Ежечасный health-check'), { target: { value: 'New canary' } });
  fireEvent.click(within(dialog).getByRole('button', { name: /one.shot/i }));
  const pipeline = within(dialog).getAllByRole('combobox').find(el => el.textContent?.includes('Выбери pipeline'))!;
  fireEvent.change(pipeline, { target: { value: 'pipeline-1' } });
  expect(within(dialog).getByRole('button', { name: 'Создать расписание' })).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText('Дата и время запуска (UTC)'), { target: { value: '2026-10-22T10:30' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Создать расписание' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/schedules', expect.objectContaining({ one_shot_at: '2026-10-22T10:30:00.000Z' })));
});

it('blocks an invalid stored instant, reports it, and permits an explicitly corrected UTC value', async () => {
  const original = jest.mocked(api.get).getMockImplementation()!;
  jest.mocked(api.get).mockImplementation((url, config) => url.startsWith('/schedules?')
    ? Promise.resolve({ data: { items: [{ ...schedule, one_shot_at: 'malformed-time' }], total: 1 } }) as never : original(url, config));
  const dialog = await openSchedule();
  expect(within(dialog).getByRole('alert')).toHaveTextContent('Дата запуска API некорректна');
  expect(within(dialog).getByRole('button', { name: 'Сохранить изменения' })).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText('Дата и время запуска (UTC)'), { target: { value: '2026-10-22T10:30' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить изменения' }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/schedules/schedule-1', expect.objectContaining({ one_shot_at: '2026-10-22T10:30:00.000Z' })));
});
