import { render, screen, within } from '@testing-library/react';
import { ActionContractCard } from '@/src/features/scripts/studio/ActionContractCard';

it('shows actual required fields, missing inputs and Android boundaries without adding defaults', () => {
  const action = { type: 'tap' };
  render(<ActionContractCard action={action} />);
  const card = screen.getByRole('region', { name: 'Контракт действия' });
  expect(within(card).getByText('x, y')).toBeInTheDocument();
  expect(within(card).getByText(/Исправьте перед проверкой/)).toBeInTheDocument();
  expect(within(card).getAllByText(/Требуется поле/)).toHaveLength(2);
  expect(within(card).getByText(/не проверяет границы экрана/)).toBeInTheDocument();
  expect(action).toEqual({ type: 'tap' });
});
it('distinguishes destructive effects and incomplete package without selecting a target', () => {
  render(<ActionContractCard action={{ type: 'clear_app_data', package: '' }} />);
  expect(screen.getByText('Удаление данных или остановка')).toBeInTheDocument();
  expect(screen.getByText(/Удаляет данные приложения/)).toBeInTheDocument();
  expect(screen.getByText('package')).toBeInTheDocument();
  expect(screen.queryByText(/Параметры проверены локально/)).not.toBeInTheDocument();
});
it('valid inputs report only local parameter validation and the exact conditional field name', () => {
  const action = { type: 'assert', check: 'text_contains', params: { selector: 'name', value: 'OK' } };
  render(<ActionContractCard action={action} />);
  expect(screen.getByText(/Возможности APK не проверены/)).toBeInTheDocument();
  expect(screen.getByText('check, params.selector, params.value')).toBeInTheDocument();
  expect(screen.queryByText(/Исправьте перед проверкой/)).not.toBeInTheDocument();
});
