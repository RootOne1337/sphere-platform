import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import UpdatesPage from '@/app/(dashboard)/updates/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
// Native selects isolate request ownership from Radix positioning in jsdom.
jest.mock('@/components/ui/select', () => {
  const React = require('react') as typeof import('react');
  return {
    Select: ({ value, onValueChange, children }: { value: string; onValueChange: (value: string) => void; children: React.ReactNode }) => {
      const trigger = React.Children.toArray(children).find(child => React.isValidElement(child) && (child.props as Record<string, unknown>)['aria-label']);
      const label = React.isValidElement(trigger) ? (trigger.props as Record<string, string>)['aria-label'] : undefined;
      return <select aria-label={label} value={value} onChange={event => onValueChange(event.target.value)}>{children}</select>;
    },
    SelectTrigger: () => null,
    SelectValue: () => null,
    SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => <option value={value}>{children}</option>,
  };
});

const release = (id: string, platform = 'android') => ({
  id, platform, flavor: 'dev', version_code: 10240, version_name: id,
  download_url: 'https://example.test/agent.apk', sha256: 'a'.repeat(64),
  mandatory: false, changelog: null, created_at: '2026-10-01T00:00:00Z',
});
const response = (id: string, platform = 'android') => ({ data: { releases: [release(id, platform)], total: 1 } });
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => jest.resetAllMocks());

it('does not turn an initial failed read into an empty catalog and recovers on retry', async () => {
  jest.mocked(api.get).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(response('recovered') as never);
  render(<UpdatesPage />, { wrapper: createWrapper() });
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить релизы');
  expect(screen.queryByText(/No releases yet/)).not.toBeInTheDocument();
  expect(screen.queryByText('0 releases')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку релизов' }));
  expect(await screen.findByText('vrecovered')).toBeInTheDocument();
});

it('shows empty only after a successful read', async () => {
  jest.mocked(api.get).mockResolvedValue({ data: { releases: [], total: 0 } } as never);
  render(<UpdatesPage />, { wrapper: createWrapper() });
  expect(await screen.findByText(/No releases yet/)).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('aborts an old filter read and cannot replace a newer catalog with its late result', async () => {
  const old = deferred<ReturnType<typeof response>>();
  jest.mocked(api.get).mockReturnValueOnce(old.promise as never).mockResolvedValueOnce(response('canary', 'android-canary') as never);
  render(<UpdatesPage />, { wrapper: createWrapper() });
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
  const oldSignal = jest.mocked(api.get).mock.calls[0][1]?.signal;
  fireEvent.change(screen.getByRole('combobox', { name: 'Platform filter' }), { target: { value: 'android-canary' } });
  expect(await screen.findByText('vcanary')).toBeInTheDocument();
  expect(oldSignal?.aborted).toBe(true);
  await act(async () => { old.resolve(response('old')); });
  expect(screen.queryByText('vold')).not.toBeInTheDocument();
  expect(screen.getByText('vcanary')).toBeInTheDocument();
});

it('never shows another filter catalog when the new filter read fails', async () => {
  jest.mocked(api.get).mockResolvedValueOnce(response('old') as never).mockRejectedValueOnce(new Error('offline'));
  render(<UpdatesPage />, { wrapper: createWrapper() });
  await screen.findByText('vold');
  fireEvent.change(screen.getByRole('combobox', { name: 'Platform filter' }), { target: { value: 'android-canary' } });
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.queryByText('vold')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  expect(screen.queryByText(/No releases yet/)).not.toBeInTheDocument();
});

it('hides cached action rows after refresh failure and restores them after retry', async () => {
  jest.mocked(api.get).mockResolvedValueOnce(response('cached') as never).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(response('fresh') as never);
  render(<UpdatesPage />, { wrapper: createWrapper() });
  await screen.findByText('vcached');
  fireEvent.click(screen.getByRole('button', { name: 'Обновить релизы' }));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.queryByText('vcached')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку релизов' }));
  expect(await screen.findByText('vfresh')).toBeInTheDocument();
});

it('aborts the owned read on unmount', async () => {
  const pending = deferred<ReturnType<typeof response>>();
  jest.mocked(api.get).mockReturnValueOnce(pending.promise as never);
  const view = render(<UpdatesPage />, { wrapper: createWrapper() });
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
  const signal = jest.mocked(api.get).mock.calls[0][1]?.signal;
  view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => { pending.resolve(response('retired')); });
});

it('rejects a malformed catalog instead of claiming it is empty', async () => {
  jest.mocked(api.get).mockResolvedValue({ data: { total: 0 } } as never);
  render(<UpdatesPage />, { wrapper: createWrapper() });
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.queryByText(/No releases yet/)).not.toBeInTheDocument();
});
