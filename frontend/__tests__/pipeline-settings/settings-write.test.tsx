import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PipelineSettingsPage from '@/app/(dashboard)/pipeline-settings/page';
import { api } from '@/lib/api';
import { toast } from 'sonner';
import {
  type PipelineSettings, usePipelineSettings, useUpdatePipelineSettings,
} from '@/lib/hooks/usePipelineSettings';
import { createTestQueryClient, createWrapper, renderQueryHook } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), patch: jest.fn(), post: jest.fn() } }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [] } }) }));

function settings(overrides: Partial<PipelineSettings> = {}): PipelineSettings {
  return {
    id: 'settings-a', org_id: 'org-a', orchestration_enabled: true, scheduler_enabled: false,
    registration_enabled: false, farming_enabled: false, max_concurrent_registrations: 7,
    registration_script_id: null, registration_timeout_seconds: 120,
    max_concurrent_farming: 12, farming_script_id: null, farming_session_duration_seconds: 600,
    default_target_level: 20, cooldown_between_sessions_minutes: 10,
    nick_generation_enabled: true, nick_pattern: '{first_name}_{digits}',
    ban_detection_enabled: true, auto_replace_banned: true, notes: 'Server notes', meta: {},
    created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z', ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

let remote: PipelineSettings;
let read: () => Promise<{ data: PipelineSettings }>;
beforeEach(() => {
  jest.clearAllMocks();
  remote = settings();
  read = async () => ({ data: remote });
  jest.mocked(api.get).mockImplementation((url) =>
    (url === '/pipeline-settings' ? read() : Promise.resolve({ data: {} })) as never);
  jest.mocked(api.patch).mockImplementation((_, body) => {
    remote = { ...remote, ...(body as Partial<PipelineSettings>) };
    return Promise.resolve({ data: remote }) as never;
  });
  jest.mocked(api.post).mockImplementation((url, body) => {
    if (url === '/pipeline-settings/toggle/scheduler') remote = { ...remote, scheduler_enabled: (body as { enabled: boolean }).enabled };
    return Promise.resolve({ data: remote }) as never;
  });
});

async function openPage() {
  const client = createTestQueryClient();
  render(<PipelineSettingsPage />, { wrapper: createWrapper(client) });
  await screen.findByRole('textbox', { name: 'Заметки' });
  return client;
}

function save() { return screen.getByRole('button', { name: 'СОХРАНИТЬ' }); }
function notes() { return screen.getByRole('textbox', { name: 'Заметки' }); }
async function refresh() {
  await userEvent.click(screen.getByRole('button', { name: 'Обновить настройки и состояние' }));
}

it.each([401, 500])('blocks all settings writes after initial HTTP %s and restores the real baseline on retry', async (code) => {
  read = async () => { throw { response: { status: code } }; };
  render(<PipelineSettingsPage />, { wrapper: createWrapper() });
  expect(await screen.findByRole('alert')).toHaveTextContent('Настройки не загружены');
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('switch')).not.toBeInTheDocument();
  expect(api.patch).not.toHaveBeenCalled();
  expect(api.post).not.toHaveBeenCalled();
  read = async () => ({ data: remote });
  await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку настроек' }));
  expect(await screen.findByDisplayValue('Server notes')).toBeInTheDocument();
  expect(screen.getByDisplayValue('7')).toBeInTheDocument();
  expect(save()).toBeDisabled();
});

it('retains a dirty draft through a confirmed module toggle and patches only the edited field', async () => {
  await openPage();
  fireEvent.change(notes(), { target: { value: 'Operator draft' } });
  await userEvent.click(screen.getByRole('switch', { name: 'Планировщик задач' }));
  await waitFor(() => expect(screen.getByRole('switch', { name: 'Планировщик задач' })).toBeChecked());
  expect(notes()).toHaveValue('Operator draft');
  expect(save()).toBeEnabled();
  await userEvent.click(save());
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/pipeline-settings', { notes: 'Operator draft' }));
  await waitFor(() => expect(save()).toBeDisabled());
  expect(api.post).toHaveBeenCalledWith('/pipeline-settings/toggle/scheduler', { enabled: true });
});

it('uses refreshed unedited fields without overwriting them in the draft PATCH', async () => {
  await openPage();
  fireEvent.change(notes(), { target: { value: 'Keep me' } });
  remote = settings({ max_concurrent_farming: 24 });
  await refresh();
  await screen.findByDisplayValue('24');
  expect(notes()).toHaveValue('Keep me');
  expect(screen.queryByText(/Редактируемые поля изменились/)).not.toBeInTheDocument();
  await userEvent.click(save());
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/pipeline-settings', { notes: 'Keep me' }));
  expect(remote.max_concurrent_farming).toBe(24);
});

it('requires an explicit conflict choice before overwriting a server-changed field', async () => {
  await openPage();
  fireEvent.change(notes(), { target: { value: 'My draft' } });
  remote = settings({ notes: 'Another operator' });
  await refresh();
  expect(await screen.findByRole('alert')).toHaveTextContent('Редактируемые поля изменились');
  expect(notes()).toHaveValue('My draft');
  expect(save()).toBeDisabled();
  expect(api.patch).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Оставить мои правки' }));
  expect(save()).toBeEnabled();
  expect(api.patch).not.toHaveBeenCalled();
  await userEvent.click(save());
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/pipeline-settings', { notes: 'My draft' }));
});

it('accepts server values without a write when the operator discards a conflicting draft', async () => {
  await openPage();
  fireEvent.change(notes(), { target: { value: 'My draft' } });
  remote = settings({ notes: 'Another operator' });
  await refresh();
  await screen.findByRole('alert');
  await userEvent.click(screen.getByRole('button', { name: 'Принять серверные значения' }));
  expect(notes()).toHaveValue('Another operator');
  expect(save()).toBeDisabled();
  expect(api.patch).not.toHaveBeenCalled();
});

it('keeps a cached draft visible but blocks writes after a failed refresh until recovery', async () => {
  await openPage();
  fireEvent.change(notes(), { target: { value: 'Retained offline' } });
  read = async () => { throw new Error('network timeout'); };
  await refresh();
  expect(await screen.findByRole('alert')).toHaveTextContent('запись заблокирована');
  expect(notes()).toHaveValue('Retained offline');
  expect(notes()).toBeDisabled();
  expect(save()).toBeDisabled();
  expect(screen.getByRole('switch', { name: 'Планировщик задач' })).toBeDisabled();
  expect(api.patch).not.toHaveBeenCalled();
  read = async () => ({ data: remote });
  await userEvent.click(screen.getByRole('button', { name: 'Повторить загрузку настроек' }));
  await waitFor(() => expect(save()).toBeEnabled());
  expect(notes()).toHaveValue('Retained offline');
});

it('retains edits after validation failure and displays a string error before a successful retry', async () => {
  await openPage();
  fireEvent.change(notes(), { target: { value: 'Retry draft' } });
  jest.mocked(api.patch).mockRejectedValueOnce({ response: { data: { detail: [{ msg: 'validation failed' }] } } });
  await userEvent.click(save());
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Ошибка сохранения настроек'));
  expect(notes()).toHaveValue('Retry draft');
  expect(save()).toBeEnabled();
  await userEvent.click(save());
  await waitFor(() => expect(save()).toBeDisabled());
  expect(api.patch).toHaveBeenCalledTimes(2);
});

it('sends an intentional empty note as null and preserves false and zero edits', async () => {
  await openPage();
  fireEvent.change(notes(), { target: { value: '' } });
  await userEvent.click(screen.getByRole('switch', { name: 'Обнаружение банов' }));
  fireEvent.change(screen.getByDisplayValue('10'), { target: { value: '0' } });
  await userEvent.click(save());
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/pipeline-settings', {
    notes: null, ban_detection_enabled: false, cooldown_between_sessions_minutes: 0,
  }));
  await waitFor(() => expect(save()).toBeDisabled());
});

it('locks concurrent edits and toggles while saving and keeps the draft after a server-normalized response', async () => {
  await openPage();
  const pending = deferred<{ data: PipelineSettings }>();
  jest.mocked(api.patch).mockReturnValueOnce(pending.promise as never);
  fireEvent.change(notes(), { target: { value: 'Draft' } });
  await userEvent.click(save());
  await waitFor(() => expect(notes()).toBeDisabled());
  expect(save()).toBeDisabled();
  await userEvent.click(screen.getByRole('switch', { name: 'Планировщик задач' }));
  expect(api.post).not.toHaveBeenCalled();
  await act(async () => pending.resolve({ data: settings({ notes: 'Server normalized draft' }) }));
  await waitFor(() => expect(notes()).toBeEnabled());
  expect(notes()).toHaveValue('Draft');
  expect(save()).toBeDisabled();
  expect(screen.getByRole('alert')).toHaveTextContent('Редактируемые поля изменились');
});

it('cancels an older settings GET before mutation so its late response cannot replace the confirmed receipt', async () => {
  const client = createTestQueryClient();
  client.setQueryData(['pipeline-settings'], remote);
  const pending = deferred<{ data: PipelineSettings }>();
  read = () => pending.promise;
  const { result } = renderQueryHook(() => ({ query: usePipelineSettings(), update: useUpdatePipelineSettings() }), { queryClient: client });
  let refetch!: Promise<unknown>;
  act(() => { refetch = result.current.query.refetch(); });
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/pipeline-settings', expect.objectContaining({ signal: expect.any(AbortSignal) })));
  const signal = jest.mocked(api.get).mock.calls.find(([url]) => url === '/pipeline-settings')?.[1]?.signal;
  await act(async () => { await result.current.update.mutateAsync({ notes: 'Confirmed receipt' }); });
  expect(signal?.aborted).toBe(true);
  await act(async () => { pending.resolve({ data: settings() }); await refetch; });
  expect(client.getQueryData<PipelineSettings>(['pipeline-settings'])?.notes).toBe('Confirmed receipt');
});
