import { act, fireEvent, render, screen } from '@testing-library/react';
import { api } from '@/lib/api';
import { AndroidNavigationBar } from '@/src/features/stream/AndroidNavigationBar';

let token: string | null = 'fixture-token';
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: token }) }));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
beforeEach(() => { jest.clearAllMocks(); token = 'fixture-token'; jest.mocked(api.post).mockResolvedValue({ data: { output: '' } }); });
function open() { return render(<AndroidNavigationBar deviceId="remote" available isAvailable={() => true} extended />); }
it.each([['Backspace', 67], ['Delete', 112], ['Enter', 66], ['Tab', 61], ['Копировать в Android', 278], ['Вырезать в Android', 277], ['Вставить в Android', 279]])('%s sends one acknowledged Android key', async (label, code) => {
  open(); fireEvent.click(screen.getByRole('button', { name: label }));
  expect(api.post).toHaveBeenCalledWith('/devices/remote/shell', { command: `input keyevent ${code}` }, expect.any(Object));
  expect(await screen.findByRole('status')).toHaveTextContent('выполнение подтверждено');
});
it('sends a draft supported by the installed APK, without exposing its value in the receipt', async () => {
  open(); fireEvent.change(screen.getByLabelText('Текст для Android'), { target: { value: 'hello world@2026: "ok"' } });
  fireEvent.click(screen.getByRole('button', { name: 'Ввести текст' }));
  expect(api.post).toHaveBeenCalledWith('/devices/remote/shell', { command: 'input text \'hello%sworld@2026:%s"ok"\'' }, expect.any(Object));
  expect(await screen.findByRole('status')).not.toHaveTextContent('hello world');
  expect(screen.getByLabelText('Текст для Android')).toHaveValue('');
});
it.each(['Привет', 'emoji🙂', 'two\nlines', 'literal%s', 'x'.repeat(1025),
  ...Array.from(";|&$`(){}\\<>!#~'").map(char => `prefix${char}suffix`), '\t', '\u007f'])('does not silently corrupt or send APK-rejected text', value => {
  open(); fireEvent.change(screen.getByLabelText('Текст для Android'), { target: { value } });
  expect(screen.getByRole('button', { name: 'Ввести текст' })).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.getByRole('alert')).toHaveTextContent('Команда не отправлена');
});
it('keeps the draft after unknown completion and does not retry automatically', async () => {
  jest.mocked(api.post).mockRejectedValueOnce(new Error('timeout'));
  open(); fireEvent.change(screen.getByLabelText('Текст для Android'), { target: { value: 'draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Ввести текст' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('результат не подтверждён');
  expect(screen.getByLabelText('Текст для Android')).toHaveValue('draft');
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('clears local draft on auth/target change and isolates an old in-flight reply', async () => {
  let finish!: (value: unknown) => void;
  jest.mocked(api.post).mockImplementationOnce(() => new Promise(r => { finish = r; }) as never);
  const view = open(); fireEvent.change(screen.getByLabelText('Текст для Android'), { target: { value: 'old draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Ввести текст' }));
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal as AbortSignal;
  token = 'new-token'; view.rerender(<AndroidNavigationBar deviceId="other" available isAvailable={() => true} extended />);
  expect(signal.aborted).toBe(true);
  expect(screen.getByLabelText('Текст для Android')).toHaveValue('');
  await act(async () => { finish({ data: { output: '' } }); });
  expect(screen.getByRole('status')).not.toHaveTextContent('выполнение подтверждено');
});
