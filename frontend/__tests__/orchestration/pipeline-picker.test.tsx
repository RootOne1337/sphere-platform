import { useState } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { PipelineCatalogPicker } from '@/components/orchestration/PipelineCatalogPicker';
import OrchestrationPage from '@/app/(dashboard)/orchestration/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [] } }) }));
jest.mock('@/components/sphere/DeviceSelector', () => ({ DeviceSelector: () => null }));
const envelope = (page: number) => ({ data: { page, per_page: 100, total: 101, pages: 2, items: [{ id: `pipeline-${page}`, name: `Catalog choice ${page}`, version: 2, is_active: true, steps: [], tags: [] }] } });
function Harness({ initial = '' }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return <PipelineCatalogPicker value={value} onChange={setValue} enabled />;
}
beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(api.get).mockImplementation(async (_url, config) => envelope((config?.params as { page?: number })?.page ?? 1) as never);
});

it('selects a target from page two and retains its ID and label while browsing and filtering other results', async () => {
  render(<Harness />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Следующая страница: конвейеры для расписания' }));
  await screen.findByRole('option', { name: 'Catalog choice 2 (v2)' });
  fireEvent.change(screen.getByLabelText('Конвейер расписания'), { target: { value: 'pipeline-2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Предыдущая страница: конвейеры для расписания' }));
  await screen.findByRole('option', { name: 'Catalog choice 1 (v2)' });
  expect(screen.getByLabelText('Конвейер расписания')).toHaveValue('pipeline-2');
  expect(screen.getByRole('option', { name: 'Catalog choice 2 (v2) — сохранённая цель' })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Поиск конвейера на странице выбора'), { target: { value: 'unmatched' } });
  expect(screen.getByLabelText('Конвейер расписания')).toHaveValue('pipeline-2');
  expect(api.post).not.toHaveBeenCalled();
});

it('keeps an existing schedule ID outside the current catalog rather than silently choosing the first result', async () => {
  render(<Harness initial="pipeline-outside" />, { wrapper: createWrapper() });
  await screen.findByRole('option', { name: 'Catalog choice 1 (v2)' });
  expect(screen.getByLabelText('Конвейер расписания')).toHaveValue('pipeline-outside');
  expect(screen.getByRole('option', { name: 'pipeline-outside — сохранённая цель' })).toBeInTheDocument();
});

it('reports a failed lookup separately, disables unconfirmed choices, and retries without erasing the selected ID', async () => {
  jest.mocked(api.get).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(envelope(1) as never);
  render(<Harness initial="pipeline-outside" />, { wrapper: createWrapper() });
  expect(await screen.findByRole('alert')).toHaveTextContent('Сохранённый ID не изменён');
  expect(screen.getByLabelText('Конвейер расписания')).toBeDisabled();
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить выбор конвейера' }));
  await screen.findByRole('option', { name: 'Catalog choice 1 (v2)' });
  expect(screen.getByLabelText('Конвейер расписания')).toHaveValue('pipeline-outside');
});

it('does not read a closed picker until it is enabled', async () => {
  const view = render(<PipelineCatalogPicker value="" onChange={jest.fn()} enabled={false} />, { wrapper: createWrapper() });
  expect(api.get).not.toHaveBeenCalled();
  view.rerender(<PipelineCatalogPicker value="" onChange={jest.fn()} enabled />);
  await screen.findByRole('option', { name: 'Catalog choice 1 (v2)' });
});

it('uses the paginated picker in the actual edit form and saves its unchanged out-of-page target ID', async () => {
  const schedule = { id: 'schedule-1', name: 'Saved target', pipeline_id: 'pipeline-outside', target_type: 'pipeline', interval_seconds: 60, timezone: 'UTC', is_active: true, conflict_policy: 'skip', total_runs: 0 };
  jest.mocked(api.get).mockImplementation(async (url, config) => url === '/pipelines' ? envelope((config?.params as { page?: number })?.page ?? 1) as never : { data: { page: 1, per_page: 100, total: url === '/schedules' ? 1 : 0, pages: url === '/schedules' ? 1 : 0, items: url === '/schedules' ? [schedule] : [] } } as never);
  jest.mocked(api.patch).mockResolvedValue({ data: schedule });
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  fireEvent.click(await screen.findByTitle('Редактировать'));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByLabelText('Конвейер расписания')).toHaveValue('pipeline-outside');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить изменения' }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/schedules/schedule-1', expect.objectContaining({ pipeline_id: 'pipeline-outside' })));
});
