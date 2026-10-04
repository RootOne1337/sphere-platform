import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '@/lib/api';
import { toast } from 'sonner';
import { RunScriptTab } from '@/src/features/devices/RunScriptTab';
import { LogcatViewer } from '@/src/features/devices/LogcatViewer';
import { WebTerminal } from '@/src/features/devices/WebTerminal';
import { interactiveResult } from '@/src/features/devices/interactiveResult';

jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock('@xterm/xterm/css/xterm.css', () => ({}));
let mockInput: ((input: string) => Promise<void>) | null = null;
const mockWrite = jest.fn(); const mockWriteln = jest.fn(); const mockDispose = jest.fn();
jest.mock('@xterm/xterm', () => ({ Terminal: class {
  loadAddon() {} open() {} write = mockWrite; writeln = mockWriteln; dispose = mockDispose;
  onData(callback: (input: string) => Promise<void>) { mockInput = callback; return { dispose: jest.fn() }; }
} }));
jest.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }));
const mockPost = api.post as jest.Mock;
beforeEach(() => { jest.clearAllMocks(); mockInput = null; });

it('accepts an explicitly empty successful result but rejects an incomplete envelope', () => {
  expect(interactiveResult({ output: '' }, 'output')).toBe('');
  expect(() => interactiveResult({}, 'output')).toThrow();
  expect(() => interactiveResult({ output: 'partial', error: 'failed' }, 'output')).toThrow('failed');
});

it('stops subsequent shell commands after device failure and never shows success', async () => {
  const user = userEvent.setup();
  mockPost.mockResolvedValueOnce({ data: { error: 'denied by device' } });
  render(<RunScriptTab deviceId="dev-1" deviceName="Fixture" isOnline onBack={() => {}} />);
  await user.type(screen.getByRole('textbox', { name: 'Команды shell: по одной на строку' }), 'getprop\nsecond-command');
  await user.click(screen.getByRole('button', { name: 'Выполнить' }));
  expect(mockPost).toHaveBeenCalledTimes(1);
  expect(mockPost).toHaveBeenCalledWith('/devices/dev-1/shell', { command: 'getprop' }, expect.objectContaining({ timeout: 35_000 }));
  expect(toast.success).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith('Скрипт завершился с ошибкой', expect.any(Object));
});

it('does not send a second command after the panel closes while a result is pending', async () => {
  let finish!: (value: unknown) => void;
  mockPost.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  const { unmount } = render(<RunScriptTab deviceId="dev-1" deviceName="Fixture" isOnline onBack={() => {}} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'first\nsecond' } });
  fireEvent.click(screen.getByRole('button', { name: 'Выполнить' }));
  unmount();
  await act(async () => finish({ data: { output: 'first completed' } }));
  expect(mockPost).toHaveBeenCalledTimes(1);
  expect(toast.success).not.toHaveBeenCalled();
});

it('does not mistake comments-only text for an executed script', async () => {
  render(<RunScriptTab deviceId="dev-1" deviceName="Fixture" isOnline onBack={() => {}} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '# comment' } });
  fireEvent.click(screen.getByRole('button', { name: 'Выполнить' }));
  expect(mockPost).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith('Нет команд для исполнения');
});

it('shows incomplete Logcat responses as errors and clears a valid empty response', async () => {
  const user = userEvent.setup();
  mockPost.mockResolvedValueOnce({ data: { logcat: 'old snapshot' } }).mockResolvedValueOnce({ data: {} }).mockResolvedValueOnce({ data: { logcat: '' } });
  render(<LogcatViewer deviceId="dev-1" />);
  expect(await screen.findByText('old snapshot')).toBeInTheDocument();
  expect(mockPost).toHaveBeenCalledWith('/devices/dev-1/logcat', { lines: 500, mode: 'sphere' }, expect.objectContaining({ timeout: 20_000 }));
  await user.click(screen.getByRole('button', { name: 'Запросить снова' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('неполный результат');
  await user.click(screen.getByRole('button', { name: 'Запросить снова' }));
  expect(await screen.findByText('APK вернул пустой журнал.')).toBeInTheDocument();
  expect(screen.queryByText('old snapshot')).not.toBeInTheDocument();
});

it('does not send a Logcat command when freshness disables management', () => {
  render(<LogcatViewer deviceId="dev-1" enabled={false} />);
  expect(mockPost).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Запросить снова' })).toBeDisabled();
});

it('never invents a connected shell session and waits for real command responses', async () => {
  mockPost.mockResolvedValueOnce({ data: { output: '' } });
  render(<WebTerminal deviceId="dev-1" />);
  expect(mockPost).not.toHaveBeenCalled();
  expect(mockWriteln.mock.calls.flat().join('\n')).not.toMatch(/Connected|Secure Shell Active/);
  await act(async () => { await mockInput?.('getprop'); await mockInput?.('\r'); });
  expect(mockPost).toHaveBeenCalledTimes(1);
  expect(mockWriteln).toHaveBeenCalledWith('[Результат получен от API]');
});

it('blocks a terminal command after freshness is lost and cleans up late responses', async () => {
  const { rerender, unmount } = render(<WebTerminal deviceId="dev-1" />);
  rerender(<WebTerminal deviceId="dev-1" enabled={false} />);
  await act(async () => { await mockInput?.('id'); await mockInput?.('\r'); });
  expect(mockPost).not.toHaveBeenCalled();
  unmount(); expect(mockDispose).toHaveBeenCalledTimes(1);
});

it('does not interpret remote terminal control codes or multi-line pasted commands', async () => {
  mockPost.mockResolvedValueOnce({ data: { output: 'normal\x1b[31m\x9b2J\x9d0;title\x07\nnext' } });
  render(<WebTerminal deviceId="dev-1" />);
  await act(async () => { await mockInput?.('first\nsecond'); await mockInput?.('\r'); });
  expect(mockPost).not.toHaveBeenCalled();
  await act(async () => { await mockInput?.('getprop'); await mockInput?.('\r'); });
  const output = mockWriteln.mock.calls.flat().join('\n');
  expect(output).not.toMatch(/[\x1b\x07\x9b\x9d]/);
  expect(output).toContain('next');
});
