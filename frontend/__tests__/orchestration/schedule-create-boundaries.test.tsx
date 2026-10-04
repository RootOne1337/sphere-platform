import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import OrchestrationPage from '@/app/(dashboard)/orchestration/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [] } }) }));
jest.mock('@/components/sphere/DeviceSelector', () => ({ DeviceSelector: ({ value, onChange }: { value: string[]; onChange: (ids: string[]) => void }) => <button onClick={() => onChange(value.length ? [] : ['device-1'])}>Переключить тестовую цель</button> }));
beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(api.get).mockImplementation(async url => ({ data: { items: url === '/pipelines' ? [{ id: 'pipeline-1', name: 'Canary', steps: [], version: 1, tags: [], is_active: true }] : [], total: url === '/pipelines' ? 1 : 0, page: 1, per_page: 100, pages: url === '/pipelines' ? 1 : 0 } }) as never);
  jest.mocked(api.post).mockResolvedValue({ data: { id: 'created' } });
});
async function openCreate() {
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  fireEvent.click(screen.getByRole('button', { name: 'Новое расписание' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.change(within(dialog).getByPlaceholderText('Ежечасный health-check'), { target: { value: 'Canary' } });
  fireEvent.change(within(dialog).getAllByRole('combobox').find(el => el.textContent?.includes('Выбери pipeline'))!, { target: { value: 'pipeline-1' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'INTERVAL' }));
  return dialog;
}

it('does not submit a schedule without device targeting and sends the explicitly selected IDs', async () => {
  const dialog = await openCreate();
  const save = within(dialog).getByRole('button', { name: 'Создать расписание' });
  expect(save).toBeDisabled();
  fireEvent.click(save); expect(api.post).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Переключить тестовую цель' }));
  expect(save).toBeEnabled(); fireEvent.click(save);
  await waitFor(() => expect(api.post).toHaveBeenCalledWith('/schedules', expect.objectContaining({ device_ids: ['device-1'], interval_seconds: 3600 })));
});

test.each([59, 86401, 60.5])('rejects interval %s instead of relying on a predictable 422 from backend', async value => {
  const dialog = await openCreate();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Переключить тестовую цель' }));
  fireEvent.change(within(dialog).getByLabelText('Интервал запуска в секундах'), { target: { value } });
  expect(within(dialog).getByRole('button', { name: 'Создать расписание' })).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});

it('accepts both inclusive interval boundaries and disables save after deselecting the only target', async () => {
  const dialog = await openCreate();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Переключить тестовую цель' }));
  for (const value of [60, 86400]) {
    fireEvent.change(within(dialog).getByLabelText('Интервал запуска в секундах'), { target: { value } });
    expect(within(dialog).getByRole('button', { name: 'Создать расписание' })).toBeEnabled();
  }
  fireEvent.click(within(dialog).getByRole('button', { name: 'Переключить тестовую цель' }));
  expect(within(dialog).getByRole('button', { name: 'Создать расписание' })).toBeDisabled();
});
