import { fireEvent, render, screen, within } from '@testing-library/react';
import OrchestrationPage from '@/app/(dashboard)/orchestration/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/components/sphere/DeviceSelector', () => ({ DeviceSelector: () => null }));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [
  { id: 'canonical', name: 'Canonical graph', current_version: { dag: { nodes: [{}, {}] } } },
  { id: 'unknown', name: 'No graph available', current_version: null },
] } }) }));

it('shows canonical step count or an explicit unknown in the actual schedule script picker', async () => {
  jest.mocked(api.get).mockResolvedValue({ data: { items: [], total: 0, page: 1, per_page: 100, pages: 0 } } as never);
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByText('Schedules'));
  fireEvent.click(screen.getByRole('button', { name: 'Новое расписание' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button', { name: /Script/ }));
  expect(within(dialog).getByRole('option', { name: 'Canonical graph (2 шага)' })).toBeInTheDocument();
  expect(within(dialog).getByRole('option', { name: 'No graph available (Шаги не указаны)' })).toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});
