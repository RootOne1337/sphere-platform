import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import DiscoveryPage from '@/app/(dashboard)/discovery/page';
import { api } from '@/lib/api';
import { createTestQueryClient, createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));

const host = '00000000-0000-4000-8000-000000000001';
const original = { subnet: '192.168.1.0/24', port_range: [5554, 5584], timeout_ms: 500,
  workstation_id: host, auto_register: false };
const empty = { scanned: 8, found: 0, registered: 0, devices: [], duration_ms: 12 };
const body = (data = empty) => ({ data });
function configure() {
  // The before archive lacks this required backend field. The same interactions
  // continue there to expose both the contract and result ownership failures.
  const workstation = screen.queryByRole('textbox', { name: 'ID существующего PC Agent · UUID' });
  if (workstation) fireEvent.change(workstation, { target: { value: host } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Порты ADB' }), { target: { value: '5554,5584' } });
  const registration = screen.getByRole('checkbox');
  if ((registration as HTMLInputElement).checked) fireEvent.click(registration);
}
const start = () => fireEvent.click(screen.getByRole('button', { name: 'Начать поиск' }));
beforeEach(() => jest.resetAllMocks());
afterEach(() => jest.useRealTimers());

it('does not dispatch a network scan merely by rendering the page', () => {
  render(<DiscoveryPage />, { wrapper: createWrapper() });
  expect(api.post).not.toHaveBeenCalled();
});

it('requires a PC Agent only for the additional legacy scan and sends the real backend contract', async () => {
  jest.mocked(api.post).mockResolvedValue(body() as never);
  render(<DiscoveryPage />, { wrapper: createWrapper() });
  expect(screen.getByRole('link', { name: 'Открыть парк устройств' })).toHaveAttribute('href', '/devices');
  expect(screen.getByRole('button', { name: 'Начать поиск' })).toBeDisabled();
  configure();
  start();
  await screen.findByText('Результаты поиска');
  expect(api.post).toHaveBeenCalledWith('/discovery/scan', original);
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('keeps the completed response bound to submitted CIDR, ports, host and registration when the form changes', async () => {
  jest.mocked(api.post).mockResolvedValue(body() as never);
  render(<DiscoveryPage />, { wrapper: createWrapper() });
  configure(); start();
  await screen.findByText('Результаты поиска');
  fireEvent.change(screen.getByRole('textbox', { name: 'Подсеть · CIDR' }), { target: { value: '10.2.0.0/24' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Порты ADB' }), { target: { value: '6000,6001' } });
  fireEvent.click(screen.getByRole('checkbox'));
  expect(screen.getByText('192.168.1.0/24')).toBeInTheDocument();
  expect(screen.queryByText('10.2.0.0/24')).not.toBeInTheDocument();
  expect(screen.getByText(/PC Agent: .*порты 5554–5584 · без регистрации/)).toBeInTheDocument();
  expect(screen.getByText(/Ответ получен: .*объём запроса 8 адресов\/портов · 12 мс/)).toBeInTheDocument();
});

it('does not label a delayed response using edits made while its request was pending', async () => {
  let resolve!: (value: ReturnType<typeof body>) => void;
  jest.mocked(api.post).mockImplementation(() => new Promise(result => { resolve = result; }) as never);
  render(<DiscoveryPage />, { wrapper: createWrapper() });
  configure(); start();
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByRole('textbox', { name: 'Подсеть · CIDR' }), { target: { value: '10.3.0.0/24' } });
  await act(async () => { resolve(body()); });
  expect(await screen.findByText('192.168.1.0/24')).toBeInTheDocument();
  expect(screen.queryByText('10.3.0.0/24')).not.toBeInTheDocument();
});

it('distinguishes existing, newly registered and scan-only devices using the actual response fields', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { scanned: 8, found: 3, registered: 1, duration_ms: 4, devices: [
    { ip: '192.168.1.1', port: 5555, serial: 'existing', model: null, already_registered: true, registered_id: 'existing-id' },
    { ip: '192.168.1.2', port: 5555, serial: 'new', model: 'Emulator', already_registered: false, registered_id: 'new-id' },
    { ip: '192.168.1.3', port: 5555, serial: 'unregistered', model: null, already_registered: false, registered_id: null },
  ] } } as never);
  render(<DiscoveryPage />, { wrapper: createWrapper() });
  configure(); fireEvent.click(screen.getByRole('checkbox')); start();
  expect(await screen.findByText('Добавлено в Sphere')).toBeInTheDocument();
  expect(screen.getByText('Уже было в Sphere')).toBeInTheDocument();
  expect(screen.getByText('Не зарегистрировано')).toBeInTheDocument();
  expect(screen.getByText('Добавлено: 1')).toBeInTheDocument();
  expect(api.post).toHaveBeenCalledWith('/discovery/scan', { ...original, auto_register: true });
  expect(screen.getByText(/Поиск добавит новые найденные устройства/)).toBeInTheDocument();
});

it.each(['5555x,5584', '5554.5,5584', '5584,5554', '5554,70000'])('blocks malformed or reversed port ranges: %s', ports => {
  render(<DiscoveryPage />, { wrapper: createWrapper() });
  configure();
  fireEvent.change(screen.getByRole('textbox', { name: 'Порты ADB' }), { target: { value: ports } });
  expect(screen.getByRole('button', { name: 'Начать поиск' })).toBeDisabled();
  start();
  expect(api.post).not.toHaveBeenCalled();
});

it('treats malformed response data as an unknown result rather than an empty scan', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { ...empty, found: 2 } } as never);
  render(<DiscoveryPage />, { wrapper: createWrapper() });
  configure(); start();
  await screen.findByRole('alert');
  expect(screen.queryByText('Устройства не найдены')).not.toBeInTheDocument();
  expect(screen.queryByText('Результаты поиска')).not.toBeInTheDocument();
});

it('never inherits automatic mutation retries and manually repeats the original scan after form edits', async () => {
  jest.useFakeTimers();
  jest.mocked(api.post).mockRejectedValueOnce(new Error('lost response')).mockResolvedValue(body() as never);
  const client = createTestQueryClient();
  client.setDefaultOptions({ ...client.getDefaultOptions(), mutations: { retry: 3, retryDelay: 1 } });
  render(<DiscoveryPage />, { wrapper: createWrapper(client) });
  configure(); start();
  await act(async () => { await jest.advanceTimersByTimeAsync(100); });
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('alert')).toHaveTextContent('Автоматического повтора нет');
  fireEvent.change(screen.getByRole('textbox', { name: 'Подсеть · CIDR' }), { target: { value: '10.4.0.0/24' } });
  fireEvent.click(screen.getByRole('button', { name: 'Повторить исходный поиск' }));
  await act(async () => { await jest.advanceTimersByTimeAsync(100); });
  expect(api.post).toHaveBeenNthCalledWith(2, '/discovery/scan', original);
  expect(screen.getByText('192.168.1.0/24')).toBeInTheDocument();
});
