import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '@/lib/api';
import { DeviceFilesPanel } from '@/src/features/devices/DeviceFilesPanel';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));

const get = jest.mocked(api.get);
const post = jest.mocked(api.post);
const endpoint = '/devices/dev-1/files';
const file = { name: 'example.txt', size: 3, modified_at_ms: 1794619000000 };
const list = { version: 1, max_bytes: 262144, files: [] as typeof file[] };
const bytes = Uint8Array.of(1, 2, 3).buffer;
const digest = 'ab'.repeat(32);
const digestResult = new Uint8Array(32).fill(0xab).buffer;
const mockDigest = jest.fn();
const mockCreateURL = jest.fn();
const mockRevokeURL = jest.fn();
const originalSubtle = Object.getOwnPropertyDescriptor(globalThis.crypto, 'subtle');
const originalCreateURL = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
const originalRevokeURL = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL');

beforeEach(() => {
  jest.resetAllMocks();
  Object.defineProperty(globalThis.crypto, 'subtle', { configurable: true, value: { digest: mockDigest } });
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: mockCreateURL });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: mockRevokeURL });
  mockDigest.mockResolvedValue(digestResult);
  mockCreateURL.mockReturnValue('blob:verified');
  get.mockResolvedValue({ data: list });
});

afterAll(() => {
  const restore = (target: object, key: string, descriptor: PropertyDescriptor | undefined) => {
    if (descriptor) Object.defineProperty(target, key, descriptor);
    else Reflect.deleteProperty(target, key);
  };
  restore(globalThis.crypto, 'subtle', originalSubtle);
  restore(URL, 'createObjectURL', originalCreateURL);
  restore(URL, 'revokeObjectURL', originalRevokeURL);
});

function renderPanel(enabled = true) {
  return render(<DeviceFilesPanel deviceId="dev-1" enabled={enabled} />, { wrapper: createWrapper() });
}

function selectFile(name = file.name, contents: ArrayBuffer = bytes) {
  const selected = new File([contents], name, { type: 'application/octet-stream' });
  Object.defineProperty(selected, 'arrayBuffer', { value: () => Promise.resolve(contents) });
  fireEvent.change(screen.getByLabelText('Файл с компьютера'), { target: { files: [selected] } });
}

it('does not contact the agent if the device snapshot is offline', () => {
  renderPanel(false);
  expect(screen.getByRole('status')).toHaveTextContent('когда Android-агент на связи');
  expect(get).not.toHaveBeenCalled();
});

it('explains that a connected legacy agent does not support file exchange', async () => {
  get.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'file_exchange_unsupported' } } });
  renderPanel();
  expect(await screen.findByRole('alert')).toHaveTextContent('не поддерживает обмен файлами');
  expect(screen.queryByRole('button', { name: 'Выбрать файл' })).not.toBeInTheDocument();
});

it('publishes an upload confirmation only after an exact agent receipt, then refreshes the folder', async () => {
  get.mockResolvedValueOnce({ data: list }).mockResolvedValueOnce({ data: { ...list, files: [file] } });
  post.mockResolvedValueOnce({ data: { name: file.name, size: 3, sha256: digest } });
  renderPanel();
  await screen.findByText('Рабочая папка пока пуста.');
  selectFile();
  await userEvent.click(screen.getByRole('button', { name: 'На устройство' }));
  expect(await screen.findByText('Android подтвердил запись файла')).toBeInTheDocument();
  expect(post).toHaveBeenCalledWith(endpoint + '/' + file.name, bytes, expect.objectContaining({
    headers: { 'Content-Type': 'application/octet-stream', 'X-Content-SHA256': digest },
  }));
  expect(within(await screen.findByRole('list', { name: 'Файлы на устройстве' })).getByText(file.name)).toBeInTheDocument();
});

it('requires a fresh directory read after an ambiguous upload receipt and never resubmits automatically', async () => {
  post.mockResolvedValueOnce({ data: { name: file.name, size: 3, sha256: 'cd'.repeat(32) } });
  renderPanel();
  await screen.findByText('Рабочая папка пока пуста.');
  selectFile();
  await userEvent.click(screen.getByRole('button', { name: 'На устройство' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Результат загрузки неизвестен');
  expect(screen.getByRole('button', { name: 'На устройство' })).toBeDisabled();
  expect(screen.queryByText('Android подтвердил запись файла')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Обновить' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(screen.queryByRole('button', { name: 'На устройство' })).not.toBeInTheDocument();
  expect(get).toHaveBeenCalledTimes(2);
  expect(post).toHaveBeenCalledTimes(1);
});

it('rejects unsupported filenames and excess size before contacting the device', async () => {
  renderPanel();
  await screen.findByText('Рабочая папка пока пуста.');
  selectFile('dangerous.');
  expect(screen.getByRole('alert')).toHaveTextContent('до 120 латинских букв');
  selectFile('large.zip', new ArrayBuffer(262145));
  expect(screen.getByRole('alert')).toHaveTextContent('превышает допустимый размер');
  expect(post).not.toHaveBeenCalled();
});

it('offers a save link only for a verified download and revokes it when the panel closes', async () => {
  get.mockResolvedValueOnce({ data: { ...list, files: [file] } }).mockResolvedValueOnce({
    data: bytes, headers: {
      'content-type': 'application/octet-stream', 'content-length': '3', 'x-content-sha256': digest,
    },
  });
  const view = renderPanel();
  await userEvent.click(await screen.findByRole('button', { name: 'Скачать ' + file.name }));
  expect(await screen.findByRole('link', { name: 'Сохранить' })).toHaveAttribute('download', file.name);
  expect(get).toHaveBeenLastCalledWith(endpoint + '/' + file.name, expect.objectContaining({ responseType: 'arraybuffer' }));
  expect(mockDigest).toHaveBeenCalledWith('SHA-256', bytes);
  view.unmount();
  expect(mockRevokeURL).toHaveBeenCalledWith('blob:verified');
});

it('rejects changed bytes without creating a downloadable object URL', async () => {
  get.mockResolvedValueOnce({ data: { ...list, files: [file] } }).mockResolvedValueOnce({
    data: bytes, headers: {
      'content-type': 'application/octet-stream', 'content-length': '3', 'x-content-sha256': 'ff'.repeat(32),
    },
  });
  renderPanel();
  await userEvent.click(await screen.findByRole('button', { name: 'Скачать ' + file.name }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Контрольная сумма не совпала');
  expect(mockCreateURL).not.toHaveBeenCalled();
});
