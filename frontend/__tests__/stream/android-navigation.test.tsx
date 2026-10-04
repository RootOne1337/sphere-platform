import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '@/lib/api';
import { AndroidNavigationBar } from '@/src/features/stream/AndroidNavigationBar';

let mockAccessToken: string | null = 'fixture-token';
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: mockAccessToken }) }));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
const post = jest.mocked(api.post);

beforeEach(() => {
  post.mockReset();
  mockAccessToken = 'fixture-token';
  post.mockResolvedValue({ data: { output: '' } });
});

function setup(deviceId = 'remote/id') {
  const isAvailable = jest.fn(() => true);
  const view = render(<AndroidNavigationBar deviceId={deviceId} available isAvailable={isAvailable} />);
  return { ...view, isAvailable };
}

it.each([['Назад', 4], ['Домой', 3], ['Недавние', 187], ['Меню', 82]])(
  '%s uses the installed-agent acknowledged command contract, including empty output', async (label, code) => {
    setup();
    await userEvent.click(screen.getByRole('button', { name: label }));
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith('/devices/remote%2Fid/shell', { command: `input keyevent ${code}` }, {
      signal: expect.any(AbortSignal), timeout: 35_000,
    });
    expect(await screen.findByRole('status')).toHaveTextContent('выполнение подтверждено');
    expect(screen.getByRole('status')).toHaveTextContent('Это не задержка появления кадра');
  },
);

it('one in-flight command locks every key before a second click in the same batch', async () => {
  let finish!: (result: { data: { output: string } }) => void;
  post.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  setup();
  const back = screen.getByRole('button', { name: 'Назад' });
  const home = screen.getByRole('button', { name: 'Домой' });
  act(() => { back.click(); home.click(); back.click(); });
  expect(post).toHaveBeenCalledTimes(1);
  for (const button of screen.getAllByRole('button')) expect(button).toBeDisabled();
  expect(screen.getByRole('region', { name: 'Навигация Android' })).toHaveAttribute('aria-busy', 'true');
  await act(async () => finish({ data: { output: '' } }));
  expect(home).toBeEnabled();
});

it.each([
  { error: 'permission denied' },
  { accepted: true },
  { output: null },
  null,
])('HTTP 200 with %j does not claim completion or retry', async data => {
  post.mockResolvedValue({ data });
  setup();
  await userEvent.click(screen.getByRole('button', { name: 'Назад' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('результат не подтверждён');
  expect(screen.getByRole('alert')).toHaveTextContent('Автоповтора нет');
  expect(post).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Назад' })).toBeEnabled();
});

it('a timeout is unknown, and a subsequent explicit action is sent only once', async () => {
  post.mockRejectedValueOnce(new Error('timeout'));
  setup();
  await userEvent.click(screen.getByRole('button', { name: 'Назад' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('timeout');
  expect(post).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole('button', { name: 'Домой' }));
  expect(post).toHaveBeenCalledTimes(2);
  expect(await screen.findByRole('status')).toHaveTextContent('«Домой»: выполнение подтверждено');
});

it('checks current transport again when it closes before the disabled state renders', () => {
  const { isAvailable } = setup();
  isAvailable.mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  expect(post).not.toHaveBeenCalled();
});

it('disabled navigation sends nothing, including keyboard activation', async () => {
  render(<AndroidNavigationBar deviceId="remote" available={false} isAvailable={() => true} />);
  await userEvent.click(screen.getByRole('button', { name: 'Домой' }));
  await userEvent.keyboard('{Enter}');
  expect(post).not.toHaveBeenCalled();
});

it('uses normal focused buttons for keyboard control without stealing global keys', async () => {
  setup();
  await userEvent.keyboard('{Escape}{Backspace}{Enter}');
  expect(post).not.toHaveBeenCalled();
  screen.getByRole('button', { name: 'Назад' }).focus();
  await userEvent.keyboard('{Enter}');
  expect(post).toHaveBeenCalledTimes(1);
  expect(await screen.findByRole('status')).toHaveTextContent('«Назад»: выполнение подтверждено');
});

it.each(['device', 'session', 'unmount'])('%s change aborts the old wait and ignores its late reply', async change => {
  let finish!: (result: { data: { output: string } }) => void;
  post.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const { rerender, unmount } = setup('old-device');
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  const signal = post.mock.calls[0][2]?.signal as AbortSignal;
  if (change === 'unmount') unmount();
  else {
    if (change === 'session') mockAccessToken = 'another-session';
    rerender(<AndroidNavigationBar deviceId={change === 'device' ? 'new-device' : 'old-device'}
      available isAvailable={() => true} />);
  }
  expect(signal.aborted).toBe(true);
  await act(async () => finish({ data: { output: '' } }));
  expect(screen.queryByText(/выполнение подтверждено/)).not.toBeInTheDocument();
  expect(post).toHaveBeenCalledTimes(1);
  if (change !== 'unmount') {
    await userEvent.click(screen.getByRole('button', { name: 'Домой' }));
    expect(post.mock.calls[1][0]).toBe(`/devices/${change === 'device' ? 'new-device' : 'old-device'}/shell`);
    expect(await screen.findByRole('status')).toHaveTextContent('«Домой»: выполнение подтверждено');
  }
});
