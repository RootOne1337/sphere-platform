import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LocationsPage from '@/app/(dashboard)/locations/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), put: jest.fn() } }));

it('sends explicit empty strings when clearing an existing location and shows the confirmed empty values', async () => {
  let location = { id: 'location-a', name: 'Remote', description: 'Old description', address: 'Old address', color: '#3b82f6', total_devices: 2, online_devices: 1 };
  jest.mocked(api.get).mockImplementation(async () => ({ data: [location] }) as never);
  jest.mocked(api.put).mockImplementation(async (_, updates) => {
    location = { ...location, ...(updates as Partial<typeof location>) };
    return { data: location } as never;
  });
  render(<LocationsPage />, { wrapper: createWrapper() });
  await userEvent.click(await screen.findByRole('button', { name: 'Изменить локацию Remote' }));
  fireEvent.change(screen.getByLabelText(/Описание/), { target: { value: '   ' } });
  fireEvent.change(screen.getByLabelText('Адрес'), { target: { value: '' } });
  await userEvent.click(screen.getByRole('button', { name: 'Сохранить изменения' }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith('/locations/location-a', {
    name: 'Remote', description: '', address: '', color: '#3b82f6',
  }));
  expect(await screen.findByText('Адрес не указан')).toBeInTheDocument();
  expect(screen.getByText('Описание не добавлено')).toBeInTheDocument();
});
