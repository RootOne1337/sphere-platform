import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TaskScreenshot } from '@/components/tasks/TaskScreenshot';
import { api } from '@/lib/api';
import { createTestQueryClient, createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const key = 'tasks/task-a/device/capture/123.jpg';
const contentUrl = `/tasks/task-a/screenshots/content?key=${encodeURIComponent(key)}`;
const manifest = () => ({ task_id: 'task-a', screenshots: [{ key, url: contentUrl, unavailable_reason: null }] });

beforeEach(() => {
  jest.clearAllMocks();
  URL.createObjectURL = jest.fn(() => 'blob:authorized-image');
  URL.revokeObjectURL = jest.fn();
  jest.mocked(api.get).mockImplementation((url) => Promise.resolve({ data: url.endsWith('/screenshots')
    ? manifest() : new Blob(['image'], { type: 'image/jpeg' }) }) as never);
});

function open() {
  return render(<TaskScreenshot taskId="task-a" screenshotKey={key} />, { wrapper: createWrapper(createTestQueryClient()) });
}

it('loads only on demand, uses the authenticated client, and releases the object URL on hide', async () => {
  const view = open();
  expect(api.get).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Открыть снимок шага' }));
  expect(await screen.findByRole('img', { name: 'Снимок шага' })).toHaveAttribute('src', 'blob:authorized-image');
  expect(api.get).toHaveBeenCalledWith(contentUrl, expect.objectContaining({ responseType: 'blob', signal: expect.any(AbortSignal) }));
  await userEvent.click(screen.getByRole('button', { name: 'Скрыть снимок' }));
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:authorized-image');
  view.unmount();
});

it.each([404, 503])('shows HTTP %s and explicitly recovers the content read', async status => {
  let fail = true;
  jest.mocked(api.get).mockImplementation((url) => url.endsWith('/screenshots') ? Promise.resolve({ data: manifest() }) as never
    : fail ? Promise.reject({ response: { status } }) : Promise.resolve({ data: new Blob(['image'], { type: 'image/png' }) }) as never);
  open();
  await userEvent.click(screen.getByRole('button', { name: 'Открыть снимок шага' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(status === 404 ? 'отсутствует' : 'недоступно');
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  fail = false;
  await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку снимка' }));
  expect(await screen.findByRole('img')).toBeInTheDocument();
});

it.each(['task-b', 'external-url'])('rejects %s manifests before fetching any bytes', async mode => {
  const data = manifest();
  if (mode === 'task-b') data.task_id = 'task-b'; else data.screenshots[0].url = 'https://other.example/image';
  jest.mocked(api.get).mockResolvedValue({ data } as never);
  open();
  await userEvent.click(screen.getByRole('button', { name: 'Открыть снимок шага' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось получить список снимков');
  expect(api.get).toHaveBeenCalledTimes(1);
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it('cancels an old request on task change and never displays its late response', async () => {
  let resolve!: (response: { data: Blob }) => void;
  const pending = new Promise<{ data: Blob }>(done => { resolve = done; });
  jest.mocked(api.get).mockImplementation((url) => url.endsWith('/screenshots') ? Promise.resolve({ data: manifest() }) as never : pending as never);
  const view = open();
  await userEvent.click(screen.getByRole('button', { name: 'Открыть снимок шага' }));
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  const signal = (jest.mocked(api.get).mock.calls[1][1] as { signal: AbortSignal }).signal;
  view.rerender(<TaskScreenshot taskId="task-b" screenshotKey="new-key" />);
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve({ data: new Blob(['old'], { type: 'image/jpeg' }) }); });
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it('reports an unconfirmed screenshot without inventing an object URL', async () => {
  jest.mocked(api.get).mockResolvedValue({ data: { task_id: 'task-a', screenshots: [] } } as never);
  open();
  await userEvent.click(screen.getByRole('button', { name: 'Открыть снимок шага' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Сервер не подтвердил');
  expect(api.get).toHaveBeenCalledTimes(1);
});

it('handles decoder failure within React and reloads without destroying the controls', async () => {
  open();
  await userEvent.click(screen.getByRole('button', { name: 'Открыть снимок шага' }));
  fireEvent.error(await screen.findByRole('img'));
  expect(screen.getByRole('alert')).toHaveTextContent('не смог декодировать');
  await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку снимка' }));
  expect(await screen.findByRole('img')).toBeInTheDocument();
  expect(URL.revokeObjectURL).toHaveBeenCalled();
});

it('rejects HTML payloads and oversized images rather than rendering them', async () => {
  let oversized = false;
  jest.mocked(api.get).mockImplementation((url) => Promise.resolve({ data: url.endsWith('/screenshots') ? manifest()
    : oversized ? new Blob([new Uint8Array(5 * 1024 * 1024 + 1)], { type: 'image/jpeg' }) : new Blob(['<html>error</html>'], { type: 'text/html' }) }) as never);
  open();
  await userEvent.click(screen.getByRole('button', { name: 'Открыть снимок шага' }));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  oversized = true;
  await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку снимка' }));
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
});
