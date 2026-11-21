import { render, screen } from '@testing-library/react';
import { DeviceStatusBadge } from '@/components/sphere/DeviceStatusBadge';

it('shows connecting separately from online and offline', () => {
  render(<DeviceStatusBadge status="connecting" />);

  expect(screen.getByText('Подключение')).toBeInTheDocument();
});

it('renders maintenance as its own backend status', () => {
  render(<DeviceStatusBadge status="maintenance" />);

  expect(screen.getByText('Обслуживание')).toBeInTheDocument();
  expect(screen.queryByText('Неизвестно')).not.toBeInTheDocument();
});
