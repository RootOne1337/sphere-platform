import { fireEvent, render, screen, within } from '@testing-library/react';
import OrchestrationPage from '@/app/(dashboard)/orchestration/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/components/sphere/DeviceSelector', () => ({ DeviceSelector: () => null }));
const mockCatalog = jest.fn();
jest.mock('@/lib/hooks/useScriptCatalog', () => ({ useScriptCatalog: (params: unknown) => mockCatalog(params) }));

it('keeps the selected published script when moving to the next catalog page', async () => {
  mockCatalog.mockImplementation(({ page }) => ({ isSuccess: true, data: { total: 51, pages: 2, items: page === 1 ? [
    { id: 'canonical', name: 'Canonical graph', current_version_id: 'version', node_count: 2 },
    { id: 'unknown', name: 'No graph available', current_version_id: null, node_count: null },
  ] : [{ id: 'older', name: 'Older graph', current_version_id: 'old-version', node_count: 7 }] } }));
  jest.mocked(api.get).mockResolvedValue({ data: { items: [], total: 0, page: 1, per_page: 100, pages: 0 } } as never);
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  fireEvent.click(screen.getByRole('button', { name: 'Новое расписание' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button', { name: /Script/ }));
  expect(within(dialog).getByRole('option', { name: 'Canonical graph (2 шага)' })).toBeInTheDocument();
  expect(within(dialog).getByRole('option', { name: 'No graph available (Шаги не указаны) · нет публикации' })).toBeDisabled();
  const picker = within(dialog).getByRole('combobox', { name: 'Сценарий расписания' });
  fireEvent.change(picker, { target: { value: 'canonical' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Следующая страница: Сценарий расписания' }));
  expect(picker).toHaveValue('canonical');
  expect(within(dialog).getByRole('option', { name: 'Older graph (7 шагов)' })).toBeInTheDocument();
  expect(mockCatalog).toHaveBeenLastCalledWith({ page: 2, per_page: 50, state: 'active', query: undefined });
  expect(api.post).not.toHaveBeenCalled();
});
