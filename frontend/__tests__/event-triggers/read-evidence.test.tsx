import { fireEvent, render, screen, within } from '@testing-library/react';
import EventTriggersPage from '@/app/(dashboard)/event-triggers/page';
import { createWrapper } from '../helpers';

const mockRefetch = jest.fn();
let mockReadError = false;
const mockTrigger = { id: 'trigger-a', name: 'Disabled by operator', is_active: false, total_triggers: 3, event_type_pattern: 'task.*', pipeline_id: 'pipeline-a', cooldown_seconds: 10, max_triggers_per_hour: 5, last_triggered_at: null };
jest.mock('@/lib/hooks/useEventTriggers', () => ({
  useEventTriggers: () => ({ data: { items: [mockTrigger], total: 201 }, isError: mockReadError, isLoading: false, isFetching: false, refetch: mockRefetch }),
  useToggleEventTrigger: () => ({ mutate: jest.fn() }),
  useDeleteEventTrigger: () => ({ mutate: jest.fn() }),
  useCreateEventTrigger: () => ({ mutate: jest.fn() }),
  useUpdateEventTrigger: () => ({ mutate: jest.fn() }),
}));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn().mockResolvedValue({ data: { items: [] } }) } }));

beforeEach(() => { jest.clearAllMocks(); mockReadError = false; });

it('shows failed reads as unknown without empty rows, cached actions or zero metrics', () => {
  mockReadError = true;
  render(<EventTriggersPage />, { wrapper: createWrapper() });
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить триггеры');
  expect(screen.queryByText('Нет триггеров. Создайте первый!')).not.toBeInTheDocument();
  expect(screen.queryByText('Disabled by operator')).not.toBeInTheDocument();
  const card = screen.getByText('Всего по фильтру API').parentElement!;
  expect(within(card).getByText('—')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку триггеров' }));
  expect(mockRefetch).toHaveBeenCalledTimes(1);
});

it('uses the server total and distinguishes disabled triggers from execution errors', () => {
  render(<EventTriggersPage />, { wrapper: createWrapper() });
  const totalCard = screen.getByText('Всего по фильтру API').parentElement!;
  expect(within(totalCard).getByText('201')).toBeInTheDocument();
  expect(screen.queryByText('С ошибками')).not.toBeInTheDocument();
  const inactiveCard = screen.getByText('Неактивных со срабатываниями').parentElement!;
  expect(within(inactiveCard).getByText('1')).toBeInTheDocument();
  expect(screen.getByText('Срабатываний на странице')).toBeInTheDocument();
});
