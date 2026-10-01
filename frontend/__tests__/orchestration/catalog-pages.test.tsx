import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import OrchestrationPage from '@/app/(dashboard)/orchestration/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [] } }) }));
jest.mock('@/components/sphere/DeviceSelector', () => ({ DeviceSelector: () => null }));
jest.mock('@/components/orchestration/PipelineResumeControl', () => ({ PipelineResumeControl: () => null }));

const pipeline = (id: string) => ({ id, name: `Pipeline ${id}`, description: null, steps: [], tags: [], version: 1, is_active: true, updated_at: '2026-10-01T10:00:00Z' });
const run = (id: string, status = 'completed') => ({ id, pipeline_id: 'pipeline-outside-page', device_id: 'device-1', status, current_step_id: null, step_logs: [], created_at: '2026-10-01T10:00:00Z' });
const schedule = (id: string) => ({ id, name: `Schedule ${id}`, target_type: 'pipeline', pipeline_id: 'pipeline-outside-page', is_active: true, total_runs: 1, conflict_policy: 'skip' });
const envelope = (page: number, items: unknown[], total = 101) => ({ data: { items, total, page, per_page: 100, pages: Math.ceil(total / 100) } });
const resource = (url: string) => url.split('?')[0];
const params = (config?: { params?: unknown }) => (config?.params ?? {}) as { page?: number; active_only?: boolean; status?: string };
beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(api.get).mockImplementation(async (url, config) => {
    const page = params(config).page ?? 1;
    const items = resource(url) === '/pipelines' ? [pipeline(`pipeline-page-${page}`)] : resource(url) === '/schedules' ? [schedule(`schedule-page-${page}`)] : [run(`run-page-${page}`)];
    return envelope(page, items) as never;
  });
});

test.each([
  ['Pipelines', 'конвейеры', 'Pipeline pipeline-page-2', '/pipelines'],
  ['Pipeline Runs', 'запуски конвейеров', 'run-page-2', '/pipelines/runs'],
  ['Schedules', 'расписания', 'Schedule schedule-page-2', '/schedules'],
])('makes record 101 reachable in %s and retains server totals', async (tab, label, entry, path) => {
  jest.mocked(api.get).mockImplementation(async (url, config) => {
    const page = params(config).page ?? 1;
    const make = resource(url) === '/pipelines' ? pipeline : resource(url) === '/schedules' ? schedule : run;
    const prefix = resource(url) === '/pipelines' ? 'pipeline' : resource(url) === '/schedules' ? 'schedule' : 'run';
    return envelope(page, page === 1 ? Array.from({ length: 100 }, (_, index) => make(`${prefix}-page-1-${index}`)) : [make(`${prefix}-page-2`)]) as never;
  });
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(`^${tab}`) }));
  const nav = await screen.findByRole('navigation', { name: `Страницы: ${label}` });
  expect(nav).toHaveTextContent('Страница 1 из 2 · всего 101');
  fireEvent.click(within(nav).getByRole('button', { name: `Следующая страница: ${label}` }));
  await screen.findByText(entry, { exact: false });
  expect(screen.getByRole('navigation', { name: `Страницы: ${label}` })).toHaveTextContent('Страница 2 из 2 · всего 101');
  expect(api.get).toHaveBeenCalledWith(path, { params: { page: 2, per_page: 100 }, signal: expect.any(AbortSignal) });
  expect(api.post).not.toHaveBeenCalled();
});

it('keeps each tab page independent and labels text search as applying to the loaded page', async () => {
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Следующая страница: конвейеры' }));
  await screen.findByText('Pipeline pipeline-page-2');
  fireEvent.change(screen.getByRole('textbox', { name: 'Поиск на текущей странице' }), { target: { value: 'page-1' } });
  expect(screen.queryByText('Pipeline pipeline-page-2')).not.toBeInTheDocument();
  expect(screen.getByText(/Текстовый поиск применяется только к текущей странице/)).toBeInTheDocument();
  expect(screen.getByRole('navigation', { name: 'Страницы: конвейеры' })).toHaveTextContent('всего 101');
  fireEvent.click(screen.getByText('Schedules'));
  await screen.findByText('Schedule schedule-page-1');
  expect(screen.getByRole('textbox', { name: 'Поиск на текущей странице' })).toHaveValue('');
  fireEvent.click(screen.getByRole('button', { name: /^Pipelines/ }));
  await screen.findByText('Pipeline pipeline-page-2');
  const previousRead = jest.mocked(api.get).getMockImplementation()!;
  jest.mocked(api.get).mockImplementation((url, config) => url === '/pipelines/runs' ? Promise.resolve(envelope(1, [{ ...run('named-run'), pipeline_id: 'pipeline-page-2' }])) as never : previousRead(url, config));
  // Refresh the independent runs catalog; names already known from pipelines remain searchable.
  fireEvent.click(screen.getByText('Pipeline Runs'));
  fireEvent.click(screen.getByRole('button', { name: 'Обновить текущий каталог' }));
  await screen.findByText('named-run', { exact: false });
  fireEvent.change(screen.getByRole('textbox', { name: 'Поиск на текущей странице' }), { target: { value: 'Pipeline pipeline-page-2' } });
  expect(screen.getByText('named-run', { exact: false })).toBeInTheDocument();
});

it('uses the global active queue and status filters, resets its page and ignores a cancelled old response', async () => {
  let resolve!: (value: ReturnType<typeof envelope>) => void;
  jest.mocked(api.get).mockImplementation(async (url, config) => {
    if (resource(url) !== '/pipelines/runs') return envelope(1, []) as never;
    if (params(config).active_only) return new Promise(r => { resolve = r; }) as never;
    const page = params(config).page ?? 1;
    return envelope(page, [run(params(config).status === 'failed' ? 'failed-id' : `run-page-${page}`, params(config).status ?? 'completed')]) as never;
  });
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Pipeline Runs'));
  fireEvent.click(await screen.findByRole('button', { name: 'Следующая страница: запуски конвейеров' }));
  await screen.findByText('run-page-2', { exact: false });
  fireEvent.change(screen.getByLabelText('Серверный фильтр запусков'), { target: { value: 'active' } });
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/pipelines/runs', { params: { page: 1, per_page: 100, active_only: true }, signal: expect.any(AbortSignal) }));
  const signal = jest.mocked(api.get).mock.calls.find(([url, config]) => url === '/pipelines/runs' && params(config).active_only)![1]!.signal;
  fireEvent.change(screen.getByLabelText('Серверный фильтр запусков'), { target: { value: 'failed' } });
  await screen.findByText('failed-id', { exact: false });
  expect(signal?.aborted).toBe(true);
  await act(async () => resolve(envelope(1, [run('late-active', 'running')])));
  expect(screen.queryByText('late-active', { exact: false })).not.toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/pipelines/runs', { params: { page: 1, per_page: 100, status: 'failed' }, signal: expect.any(AbortSignal) });
});

it('keeps server totals distinct from page aggregates and hides stale counters and actions after a failed read', async () => {
  const previousRead = jest.mocked(api.get).getMockImplementation()!;
  jest.mocked(api.get).mockImplementation((url, config) => resource(url) === '/pipelines/runs' ? Promise.resolve(envelope(1, [run('paused-in-queue', 'paused')])) as never : previousRead(url, config));
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  await screen.findByText('Pipeline pipeline-page-1');
  expect(within(screen.getByText('Pipelines в каталоге').parentElement!).getByText('101')).toBeInTheDocument();
  expect(within(screen.getByText('Активная очередь · страница 1').parentElement!).getByText('1')).toBeInTheDocument();
  expect(screen.getByText(/Счётчики запусков и активных расписаний относятся к загруженным страницам/)).toBeInTheDocument();
  jest.mocked(api.get).mockRejectedValue(new Error('offline'));
  fireEvent.click(screen.getByRole('button', { name: 'Обновить текущий каталог' }));
  await screen.findByText('Не удалось обновить Конвейеры.');
  expect(screen.queryByText('Pipeline pipeline-page-1')).not.toBeInTheDocument();
  expect(within(screen.getByText('Pipelines в каталоге').parentElement!).getByText('—')).toBeInTheDocument();
  expect(screen.queryByRole('navigation', { name: 'Страницы: конвейеры' })).not.toBeInTheDocument();
});

it('rejects the wrong page envelope instead of presenting foreign rows or confirmed empty data', async () => {
  jest.mocked(api.get).mockImplementation(async (url) => envelope(resource(url) === '/pipelines' ? 2 : 1, resource(url) === '/pipelines' ? [pipeline('wrong-page')] : []) as never);
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  await screen.findByText('Не удалось обновить Конвейеры.');
  expect(screen.queryByText('Pipeline wrong-page')).not.toBeInTheDocument();
  expect(screen.queryByText('Нет pipelines. Создайте первый!')).not.toBeInTheDocument();
});

it('returns to the remaining last page after the server catalog shrinks', async () => {
  let shrunk = false;
  jest.mocked(api.get).mockImplementation(async (url, config) => {
    if (resource(url) === '/pipelines' && params(config).page === 2) { shrunk = true; return envelope(2, [], 1) as never; }
    return envelope(1, resource(url) === '/pipelines' ? [pipeline('remaining')] : [], shrunk ? 1 : 101) as never;
  });
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Следующая страница: конвейеры' }));
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/pipelines', { params: { page: 2, per_page: 100 }, signal: expect.any(AbortSignal) }));
  await screen.findByText('Pipeline remaining');
  expect(screen.getByRole('navigation', { name: 'Страницы: конвейеры' })).toHaveTextContent('Страница 1');
});

test.each([
  ['Pipelines', 'конвейеров', '/pipelines'],
  ['Schedules', 'расписаний', '/schedules'],
])('sends an explicit server activation filter for %s without calling a filtered empty catalog globally empty', async (tab, label, path) => {
  jest.mocked(api.get).mockImplementation(async (_url, config) => envelope(1, [], (config?.params as { is_active?: boolean })?.is_active === false ? 0 : 101) as never);
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(`^${tab}`) }));
  fireEvent.change(screen.getByLabelText(`Серверный фильтр ${label}`), { target: { value: 'inactive' } });
  await screen.findByText(`По этому серверному фильтру ${label} нет.`);
  expect(api.get).toHaveBeenCalledWith(path, { params: { page: 1, per_page: 100, is_active: false }, signal: expect.any(AbortSignal) });
});

test.each([
  ['/pipelines', { ...pipeline('malformed'), steps: null }, 'Конвейеры'],
  ['/pipelines/runs', { ...run('malformed'), step_logs: null }, 'Запуски'],
  ['/schedules', { ...schedule('malformed'), name: null }, 'Расписания'],
])('treats unusable row fields from %s as a read failure before rendering actionable rows', async (path, row, label) => {
  jest.mocked(api.get).mockImplementation(async url => envelope(1, resource(url) === path ? [row] : []) as never);
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  await screen.findByText(`Не удалось обновить ${label}.`);
  expect(screen.queryByText('malformed', { exact: false })).not.toBeInTheDocument();
});
