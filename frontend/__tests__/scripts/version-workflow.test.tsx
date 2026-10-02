import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import ScriptsPage from '@/app/(dashboard)/scripts/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
jest.mock('@/components/sphere/RunScriptModal', () => ({ RunScriptModal: () => null }));
const id = '11111111-1111-4111-8111-111111111111';
const org = '22222222-2222-4222-8222-222222222222';
const oldId = '33333333-3333-4333-8333-333333333333';
const currentId = '44444444-4444-4444-8444-444444444444';
const newId = '55555555-5555-4555-8555-555555555555';
const version = (versionId: string, number: number, marker: string) => ({ id: versionId, script_id: id,
  version: number, dag: { name: marker, nodes: [{ id: 'wait', action: { type: 'wait', ms: number } }], password: 'never-render-secret' },
  dag_hash: (number === 1 ? 'a' : 'b').repeat(64), notes: marker, created_by_id: null, created_at: '2026-10-02T00:00:00Z' });
const old = version(oldId, 1, 'Original');
const current = version(currentId, 2, 'Current');
let script: ReturnType<typeof initial>;
function initial() { return { id, org_id: org, name: 'Canary scenario', description: null, is_archived: false,
  current_version_id: currentId, current_version: current, versions: [current, old],
  created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z' }; }
beforeEach(() => {
  jest.resetAllMocks(); script = initial();
  useAuthStore.setState({ accessToken: 'test', sessionVersion: 0, user: { id: 'actor', org_id: org, email: 'a@example.org', role: 'org_admin' } });
  jest.mocked(api.get).mockImplementation(async url => {
    if (url === '/scripts') return { data: { items: [script], total: 1, page: 1, per_page: 50 } } as never;
    if (url === '/scripts/' + id) return { data: { ...script, versions: script.versions.map(v => ({ ...v, dag: null })) } } as never;
    return { data: url === `/scripts/${id}/versions/${oldId}` ? old : script.current_version } as never;
  });
});
async function open() {
  render(<ScriptsPage />, { wrapper: createWrapper() });
  await screen.findByText('Canary scenario');
  fireEvent.click(screen.getByRole('button', { name: 'История и управление' }));
  const dialog = await screen.findByRole('dialog');
  await within(dialog).findByText(/SHA-256 выбранной версии/);
  return dialog;
}
async function chooseOld(dialog: HTMLElement) {
  fireEvent.change(within(dialog).getByRole('combobox', { name: 'Версия для просмотра' }), { target: { value: oldId } });
  await waitFor(() => expect(api.get).toHaveBeenCalledWith(`/scripts/${id}/versions/${oldId}`, { signal: expect.any(AbortSignal) }));
  await within(dialog).findByText(/Изменено полей/);
}

it('keeps the archive reachable with server filtering and resets pagination', async () => {
  render(<ScriptsPage />, { wrapper: createWrapper() });
  await screen.findByText('Canary scenario');
  fireEvent.click(screen.getByRole('button', { name: 'Архив' }));
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/scripts', {
    params: { query: undefined, page: 1, per_page: 50, state: 'archived' }, signal: expect.any(AbortSignal),
  }));
});
it('reads one selected immutable version and displays only redacted DAG with a change summary', async () => {
  const dialog = await open(); await chooseOld(dialog);
  expect(within(dialog).getByText(/"password": "\[скрыто\]"/)).toBeInTheDocument();
  expect(dialog.textContent).not.toContain('never-render-secret');
  expect(within(dialog).getByText('a'.repeat(64))).toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled(); expect(api.delete).not.toHaveBeenCalled();
});
it('requires explicit rollback confirmation, captures the current version and verifies its new receipt', async () => {
  const dialog = await open(); await chooseOld(dialog);
  jest.mocked(api.post).mockImplementation(async () => {
    const restored = { ...old, id: newId, version: 3, notes: 'Rollback to version 1' };
    script = { ...script, current_version_id: newId, current_version: restored, versions: [restored, ...script.versions] };
    return { status: 200, data: script } as never;
  });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Откатить к выбранной версии' }));
  expect(api.post).not.toHaveBeenCalled();
  expect(within(dialog).getByText(/создаст новую неизменяемую версию/)).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить откат' }));
  await within(dialog).findByText(/Создана версия v3/);
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith(`/scripts/${id}/versions/${oldId}/rollback`, { expected_current_version_id: currentId });
});
it('shows archive impact and uses the captured version condition', async () => {
  const dialog = await open();
  jest.mocked(api.delete).mockImplementation(async () => { script = { ...script, is_archived: true }; return { status: 204 } as never; });
  fireEvent.click(within(dialog).getByRole('button', { name: 'В архив' }));
  expect(within(dialog).getByText(/не отменяет уже созданные задания/)).toBeInTheDocument();
  expect(api.delete).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить архивирование' }));
  await within(dialog).findByText(/Архивирование подтверждено/);
  expect(api.delete).toHaveBeenCalledWith('/scripts/' + id, { params: { expected_current_version_id: currentId } });
});
it.each([403, 404, 409])('reports a refused mutation (%i) without retrying', async status => {
  const dialog = await open(); await chooseOld(dialog);
  jest.mocked(api.post).mockRejectedValue({ response: { status, data: { detail: 'do-not-display-raw-error' } } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Откатить к выбранной версии' }));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить откат' }));
  await within(dialog).findByRole('alert');
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(dialog.textContent).not.toContain('do-not-display-raw-error');
});
it('blocks repeat writes on timeout until an explicit fresh read', async () => {
  const dialog = await open(); await chooseOld(dialog);
  jest.mocked(api.post).mockRejectedValue(new Error('timeout'));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Откатить к выбранной версии' }));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить откат' }));
  await within(dialog).findByText(/Результат записи неизвестен/);
  expect(within(dialog).getByRole('button', { name: 'Откатить к выбранной версии' })).toBeDisabled();
  expect(within(dialog).getByRole('button', { name: 'В архив' })).toBeDisabled();
  expect(api.post).toHaveBeenCalledTimes(1);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Обновить состояние' }));
  await waitFor(() => expect(within(dialog).getByRole('button', { name: 'В архив' })).toBeEnabled());
});
it('rejects a wrong or malformed rollback receipt instead of announcing success', async () => {
  const dialog = await open(); await chooseOld(dialog);
  jest.mocked(api.post).mockResolvedValue({ status: 200, data: initial() } as never);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Откатить к выбранной версии' }));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить откат' }));
  await within(dialog).findByText(/Результат записи неизвестен/);
  expect(within(dialog).queryByText(/Создана версия/)).not.toBeInTheDocument();
});
it('keeps the viewer read-only', async () => {
  useAuthStore.setState({ user: { ...useAuthStore.getState().user!, role: 'viewer' } });
  const dialog = await open(); await chooseOld(dialog);
  expect(within(dialog).getByRole('button', { name: 'В архив' })).toBeDisabled();
  expect(within(dialog).getByRole('button', { name: 'Откатить к выбранной версии' })).toBeDisabled();
});
it('invalidates confirmation when a fresh read reports a new current version', async () => {
  const dialog = await open(); await chooseOld(dialog);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Откатить к выбранной версии' }));
  script = { ...script, current_version_id: newId, current_version: { ...current, id: newId, version: 3 }, versions: [{ ...current, id: newId, version: 3 }, ...script.versions] };
  fireEvent.click(within(dialog).getByRole('button', { name: 'Обновить состояние' }));
  await waitFor(() => expect(within(dialog).queryByRole('button', { name: 'Подтвердить откат' })).not.toBeInTheDocument());
  expect(api.post).not.toHaveBeenCalled();
});
it('blocks writes after a failed refresh even with cached metadata', async () => {
  const dialog = await open();
  jest.mocked(api.get).mockRejectedValue(new Error('offline'));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Обновить состояние' }));
  await within(dialog).findByText(/Не удалось прочитать сценарий/);
  expect(within(dialog).queryByRole('button', { name: 'В архив' })).not.toBeInTheDocument();
});
it('does not allow a double click to publish a second mutation', async () => {
  const dialog = await open(); await chooseOld(dialog);
  jest.mocked(api.post).mockImplementation(() => new Promise(() => undefined) as never);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Откатить к выбранной версии' }));
  const submit = within(dialog).getByRole('button', { name: 'Подтвердить откат' });
  fireEvent.click(submit); fireEvent.click(submit);
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('rejects a foreign detail instead of exposing its DAG or controls', async () => {
  jest.mocked(api.get).mockImplementation(async url => ({ data: url === '/scripts'
    ? { items: [script], total: 1, page: 1, per_page: 50 }
    : { ...script, org_id: 'foreign' } }) as never);
  render(<ScriptsPage />, { wrapper: createWrapper() });
  await screen.findByText('Canary scenario');
  fireEvent.click(screen.getByRole('button', { name: 'История и управление' }));
  const dialog = await screen.findByRole('dialog');
  await within(dialog).findByText(/Не удалось прочитать сценарий/);
  expect(within(dialog).queryByRole('button', { name: 'В архив' })).not.toBeInTheDocument();
});
it('ignores a late version read after the selected version changes', async () => {
  const dialog = await open();
  let resolveOld!: (value: unknown) => void;
  jest.mocked(api.get).mockImplementation(async url => {
    if (url.endsWith('/versions/' + oldId)) return await new Promise<unknown>(resolve => { resolveOld = resolve; }) as never;
    return { data: script.current_version } as never;
  });
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: oldId } });
  await waitFor(() => expect(resolveOld).toBeDefined());
  const call = jest.mocked(api.get).mock.calls.at(-1);
  fireEvent.change(within(dialog).getByRole('combobox'), { target: { value: currentId } });
  await act(async () => { resolveOld({ data: old }); });
  expect(call?.[1]?.signal?.aborted).toBe(true);
  expect(within(dialog).queryByText('a'.repeat(64))).not.toBeInTheDocument();
});
it('retires a pending dialog when the operator session changes', async () => {
  const dialog = await open(); await chooseOld(dialog);
  let finish!: (v: unknown) => void;
  jest.mocked(api.post).mockImplementation(() => new Promise(resolve => { finish = resolve; }) as never);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Откатить к выбранной версии' }));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить откат' }));
  await act(async () => { useAuthStore.getState().logout(); });
  await act(async () => { finish({ status: 200, data: initial() }); });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.queryByText(/Создана версия/)).not.toBeInTheDocument();
});
