import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DeviceSelector } from '@/components/sphere/DeviceSelector';
import { useDevices } from '@/lib/hooks/useDevices';

const mockUseDevices = jest.mocked(useDevices);
const mockOnChange = jest.fn();
const mockSubmit = jest.fn((event: React.FormEvent) => event.preventDefault());

jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: jest.fn() }));
jest.mock('@/lib/hooks/useGroups', () => ({
  useGroups: () => ({ data: [{ id: 'group-1', color: '#0f766e', name: 'Remote group', total_devices: 1 }] }),
}));
jest.mock('@/lib/hooks/useLocations', () => ({ useLocations: () => ({ data: [] }) }));

beforeAll(() => {
  class ResizeObserverMock implements ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(globalThis, 'ResizeObserver', { configurable: true, value: ResizeObserverMock });
  Object.defineProperty(HTMLElement.prototype, 'hasPointerCapture', { configurable: true, value: () => false });
  Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', { configurable: true, value: () => undefined });
  Object.defineProperty(HTMLElement.prototype, 'releasePointerCapture', { configurable: true, value: () => undefined });
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
});

const devices = [
  { id: 'device-1', name: 'Device 1', android_id: 'serial-1', model: 'Emulator', android_version: '9', group_ids: ['group-1'], location_ids: [], status: 'online' },
  { id: 'device-2', name: 'Device 2', android_id: 'serial-2', model: 'Emulator', android_version: '9', group_ids: [], location_ids: [], status: 'offline' },
];

function setDeviceQuery(items = devices, total = items.length) {
  mockUseDevices.mockReturnValue({
    data: { items, total, scope_total: total, page: 1, page_size: 5000, pages: Math.ceil(total / 5000) },
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: jest.fn(),
  } as never);
}

beforeEach(() => {
  jest.clearAllMocks();
  setDeviceQuery();
});

afterEach(() => {
  jest.useRealTimers();
});

it('keeps selector actions from submitting the surrounding pipeline form', async () => {
  const user = userEvent.setup();
  render(
    <form onSubmit={mockSubmit}>
      <DeviceSelector value={[]} onChange={mockOnChange} />
      <button type="submit">Save pipeline</button>
    </form>,
  );

  await user.click(screen.getByRole('button', { name: 'Выбрать все' }));

  expect(mockOnChange).toHaveBeenCalledWith(['device-1', 'device-2']);
  expect(mockSubmit).not.toHaveBeenCalled();
});

it('refuses to label a truncated API page as the full all-device target', async () => {
  const user = userEvent.setup();
  setDeviceQuery([devices[0]], 3);
  render(<DeviceSelector value={[]} onChange={mockOnChange} />);

  await user.click(screen.getByRole('combobox'));
  await user.click(await screen.findByRole('option', { name: 'Все устройства' }));

  expect(await screen.findByText(/Область не выбрана целиком: загружено 1 из 3/)).toBeInTheDocument();
  expect(screen.getByText(/Нельзя выбрать весь каталог: загружено 1 из 3/)).toBeInTheDocument();
  expect(mockOnChange).not.toHaveBeenCalledWith(['device-1']);
});

it('selects the complete server-confirmed catalog when the result is not truncated', async () => {
  const user = userEvent.setup();
  const { rerender } = render(<DeviceSelector value={[]} onChange={mockOnChange} />);

  await user.click(screen.getByRole('combobox'));
  await user.click(await screen.findByRole('option', { name: 'Все устройства' }));

  await waitFor(() => expect(mockOnChange).toHaveBeenCalledWith(['device-1', 'device-2']));
  rerender(<DeviceSelector value={['device-1', 'device-2']} onChange={mockOnChange} />);
  expect(screen.getByText('Выбраны все устройства (2)')).toBeInTheDocument();
});

it('uses server-side group filtering before selecting a whole group', async () => {
  const user = userEvent.setup();
  mockUseDevices.mockImplementation((params) => {
    const items = params.group_id ? [devices[0]] : devices;
    return {
      data: { items, total: items.length, scope_total: items.length, page: 1, page_size: 5000, pages: 1 },
      isLoading: false,
      isFetching: false,
      isError: false,
      refetch: jest.fn(),
    } as never;
  });
  render(<DeviceSelector value={[]} onChange={mockOnChange} />);

  await user.click(screen.getByRole('combobox'));
  await user.click(await screen.findByRole('option', { name: 'По группе' }));
  await user.click(screen.getAllByRole('combobox')[1]);
  await user.click(await screen.findByRole('option', { name: /Remote group \(1\)/ }));

  await waitFor(() => expect(mockOnChange).toHaveBeenCalledWith(['device-1']));
  expect(mockUseDevices).toHaveBeenLastCalledWith(expect.objectContaining({ group_id: 'group-1' }));
});

it('does not select a truncated group even when the group query returns matching devices', async () => {
  const user = userEvent.setup();
  mockUseDevices.mockImplementation((params) => {
    const items = params.group_id ? [devices[0]] : devices;
    const total = params.group_id ? 3 : devices.length;
    return {
      data: { items, total, scope_total: total, page: 1, page_size: 5000, pages: 1 },
      isLoading: false,
      isFetching: false,
      isError: false,
      refetch: jest.fn(),
    } as never;
  });
  render(<DeviceSelector value={[]} onChange={mockOnChange} />);

  await user.click(screen.getByRole('combobox'));
  await user.click(await screen.findByRole('option', { name: 'По группе' }));
  await user.click(screen.getAllByRole('combobox')[1]);
  await user.click(await screen.findByRole('option', { name: /Remote group \(1\)/ }));

  expect(await screen.findByText(/Область не выбрана целиком: загружено 1 из 3/)).toBeInTheDocument();
  expect(mockOnChange).not.toHaveBeenCalledWith(['device-1']);
});

it('sends manual search to the API before selection is enabled for the result set', async () => {
  jest.useFakeTimers();
  const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
  render(<DeviceSelector value={[]} onChange={mockOnChange} />);

  await user.type(screen.getByPlaceholderText('Имя, serial, модель или UUID…'), 'serial-1');
  expect(screen.getByRole('button', { name: 'Выбрать все' })).toBeDisabled();

  await act(async () => { jest.advanceTimersByTime(300); });
  await waitFor(() => expect(mockUseDevices).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'serial-1' })));
  expect(screen.getByRole('button', { name: 'Выбрать все' })).toBeEnabled();
});

it('fails closed on catalog errors and offers an explicit retry', async () => {
  const refetch = jest.fn();
  mockUseDevices.mockReturnValue({
    data: undefined,
    isLoading: false,
    isFetching: false,
    isError: true,
    refetch,
  } as never);
  const user = userEvent.setup();
  render(<DeviceSelector value={[]} onChange={mockOnChange} />);

  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить полный каталог устройств.');
  expect(screen.getByRole('button', { name: 'Выбрать все' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Повторить' }));
  expect(refetch).toHaveBeenCalledTimes(1);
  expect(mockOnChange).not.toHaveBeenCalled();

  await user.click(screen.getByRole('combobox'));
  await user.click(await screen.findByRole('option', { name: 'Все устройства' }));
  expect(await screen.findByText('Не удалось проверить полный состав каталога')).toBeInTheDocument();
  expect(screen.queryByText('В каталоге нет активных устройств')).not.toBeInTheDocument();
});

it('explains an empty catalog instead of presenting a selectable all target', async () => {
  const user = userEvent.setup();
  setDeviceQuery([], 0);
  render(<DeviceSelector value={[]} onChange={mockOnChange} />);

  await user.click(screen.getByRole('combobox'));
  await user.click(await screen.findByRole('option', { name: 'Все устройства' }));

  expect(await screen.findByText('В каталоге нет активных устройств')).toBeInTheDocument();
  expect(mockOnChange).toHaveBeenCalledWith([]);
});
