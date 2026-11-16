import { render, screen, within } from '@testing-library/react';
import { ScooterFiveMapRoute } from '@/src/features/stream/ScooterFiveMapRoute';

test('shows the Ariane route and the live validation state without a launch action', () => {
  render(<ScooterFiveMapRoute/>);
  const summary = screen.getByText('Scooter 5 · Вокруг Кремля');
  const details = summary.closest('details');
  expect(details).toBeInTheDocument();
  if (!details) throw new Error('Map preview is missing');
  details.open = true;
  expect(within(details).getByRole('img', { name: /Контур Scooter 5/ })).toBeVisible();
  expect(within(details).getByText(/Живой запуск ожидает проверки/)).toBeVisible();
  expect(within(details).queryByRole('button', { name: /запуск/i })).not.toBeInTheDocument();
});
