import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import LogsPage from '@/app/(dashboard)/logs/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), delete: jest.fn() } }));
let mockParams = new URLSearchParams();
const mockReplace = jest.fn();
jest.mock('next/navigation', () => ({ useSearchParams: () => mockParams, useRouter: () => ({ replace: mockReplace }) }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

const devices = Array.from({ length: 101 }, (_, index) => ({ id: `device-${index + 1}`, name: `Android ${index + 1}`, status: 'online' }));
const logs = (id: string, text = `Log from ${id}`) => ({ data: { device_id: id, lines: [text], total: 1 } });
const getPage = (config: any) => config?.params?.page ?? 1;
function setupApi() {
  jest.mocked(api.get).mockImplementation(async (url, config) => {
    if (url === '/devices') {
      const search = (config?.params as { search?: string } | undefined)?.search;
      const matches = search ? devices.filter(d => d.name.includes(search)) : devices;
      const page = getPage(config);
      return { data: { items: matches.slice((page - 1) * 100, page * 100), total: matches.length, page, per_page: 100 } } as never;
    }
    if (url.startsWith('/devices/')) return { data: devices.find(d => url.endsWith(`/${d.id}`)) } as never;
    if (url.startsWith('/logs/')) return logs(url.split('/')[2].split('?')[0]) as never;
    throw new Error(`Unexpected GET ${url}`);
  });
}
beforeEach(() => { jest.resetAllMocks(); mockParams = new URLSearchParams(); setupApi(); });
beforeAll(() => Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() }));

it('reaches the 101st device without fetching the full fleet and retains its log source across catalog paging', async () => {
  render(<LogsPage />, { wrapper: createWrapper() });
  await screen.findByText('Log from device-1');
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: источники логов' }));
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/devices', expect.objectContaining({ params: expect.objectContaining({ page: 2, per_page: 100 }) })));
  await screen.findByText('Страница 2 из 2 · всего 101');
  fireEvent.click(screen.getByRole('combobox', { name: 'Устройство для просмотра логов' }));
  fireEvent.click(await screen.findByRole('option', { name: /Android 101/ }));
  expect(await screen.findByText('Log from device-101')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Предыдущая страница: источники логов' }));
  await waitFor(() => expect(screen.getByText('Страница 1 из 2 · всего 101')).toBeInTheDocument());
  expect(screen.getByText('Log from device-101')).toBeInTheDocument();
  expect(mockReplace).toHaveBeenLastCalledWith('/logs?device_id=device-101', { scroll: false });
});

it('uses the explicit device link even when it is outside the first catalog page', async () => {
  mockParams = new URLSearchParams('device_id=device-101');
  render(<LogsPage />, { wrapper: createWrapper() });
  expect(await screen.findByText('Log from device-101')).toBeInTheDocument();
  expect(api.get).not.toHaveBeenCalledWith('/logs/device-1?lines=1000', expect.anything());
  expect(await screen.findByText('Android 101', { selector: 'span' })).toBeInTheDocument();
});

it('searches the backend catalog, resets paging and does not silently switch the currently viewed device', async () => {
  render(<LogsPage />, { wrapper: createWrapper() });
  await screen.findByText('Log from device-1');
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: источники логов' }));
  await screen.findByText('Страница 2 из 2 · всего 101');
  fireEvent.change(screen.getByRole('textbox', { name: 'Поиск источника логов во всём каталоге' }), { target: { value: 'Android 101' } });
  expect(screen.getByRole('combobox', { name: 'Устройство для просмотра логов' })).toBeDisabled();
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/devices', expect.objectContaining({ params: expect.objectContaining({ page: 1, per_page: 100, search: 'Android 101' }) })));
  expect(screen.getByText('Log from device-1')).toBeInTheDocument();
});

it('rejects a log payload for another device and leaves deletion disabled after the failed read', async () => {
  mockParams = new URLSearchParams('device_id=device-101');
  const original = jest.mocked(api.get).getMockImplementation()!;
  jest.mocked(api.get).mockImplementation((url, config) => url.startsWith('/logs/') ? Promise.resolve(logs('device-1', 'Foreign device data')) as never : original(url, config));
  render(<LogsPage />, { wrapper: createWrapper() });
  expect(await screen.findByRole('alert')).toHaveTextContent('другого устройства');
  expect(screen.queryByText('Foreign device data')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Очистить логи' })).toBeDisabled();
});

it('keeps an explicit device usable after catalog failure and shows the catalog as unknown rather than empty', async () => {
  mockParams = new URLSearchParams('device_id=device-101');
  const original = jest.mocked(api.get).getMockImplementation()!;
  jest.mocked(api.get).mockImplementation((url, config) => url === '/devices' ? Promise.reject(new Error('catalog down')) : original(url, config));
  render(<LogsPage />, { wrapper: createWrapper() });
  expect(await screen.findByText('Log from device-101')).toBeInTheDocument();
  expect(await screen.findByRole('alert')).toHaveTextContent('Каталог устройств не загрузился');
  expect(screen.queryByText('Устройств пока нет')).not.toBeInTheDocument();
});

it('ignores a late response from the previous source while the next source is loading', async () => {
  let resolveFirst!: (value: ReturnType<typeof logs>) => void;
  const first = new Promise<ReturnType<typeof logs>>(resolve => { resolveFirst = resolve; });
  const original = jest.mocked(api.get).getMockImplementation()!;
  jest.mocked(api.get).mockImplementation((url, config) => url.startsWith('/logs/device-1?') ? first as never : original(url, config));
  const view = render(<LogsPage />, { wrapper: createWrapper() });
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/logs/device-1?lines=1000', expect.anything()));
  const firstSignal = jest.mocked(api.get).mock.calls.find(([url]) => url.startsWith('/logs/device-1?'))![1]?.signal;
  mockParams = new URLSearchParams('device_id=device-101');
  view.rerender(<LogsPage />);
  expect(await screen.findByText('Log from device-101')).toBeInTheDocument();
  expect(firstSignal?.aborted).toBe(true);
  await act(async () => resolveFirst(logs('device-1', 'Late first device')));
  expect(screen.queryByText('Late first device')).not.toBeInTheDocument();
});

it('does not erase the newly selected source when a confirmed deletion of the previous device finishes late', async () => {
  let resolveDelete!: (value: any) => void;
  jest.mocked(api.delete).mockImplementation(() => new Promise(resolve => { resolveDelete = resolve; }));
  const view = render(<LogsPage />, { wrapper: createWrapper() });
  await screen.findByText('Log from device-1');
  fireEvent.click(screen.getByRole('button', { name: 'Очистить логи' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Удалить логи' }));
  await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/logs/device-1'));
  mockParams = new URLSearchParams('device_id=device-101'); view.rerender(<LogsPage />);
  await screen.findByText('Log from device-101');
  await act(async () => resolveDelete({ status: 204 }));
  expect(screen.getByText('Log from device-101')).toBeInTheDocument();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
