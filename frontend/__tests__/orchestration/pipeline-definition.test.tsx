import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { PipelineDefinitionDialog } from '@/src/features/orchestration/PipelineDefinitionDialog';
import { canonical, definitionDraft, validateDefinitionDraft, type PipelineDefinition } from '@/src/features/orchestration/pipelineDefinition';
import OrchestrationPage from '@/app/(dashboard)/orchestration/page';
import { useAuthStore } from '@/lib/store';
import { api } from '@/lib/api';
import { createTestQueryClient, createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useScripts', () => ({ useScripts: () => ({ data: { items: [] }, isLoading: false }) }));
jest.mock('@/components/sphere/DeviceSelector', () => ({ DeviceSelector: () => null }));
const id = '11111111-1111-4111-8111-111111111111';
const org = '22222222-2222-4222-8222-222222222222';
const scope = 'org:actor:admin:0';
const start = { id: 'start', name: 'Delay control', type: 'delay', params: { seconds: 1, token: 'private-parameter' }, on_success: null, on_failure: null, timeout_ms: 10000, retries: 0 };
function initial(): PipelineDefinition { return { id, org_id: org, name: 'Controlled pipeline', description: 'Initial description', steps: [start],
  input_schema: { type: 'object' }, global_timeout_ms: 30000, max_retries: 0, version: 1, is_active: true, tags: ['control'], created_by_id: null,
  created_at: '2026-10-03T00:00:00Z', updated_at: '2026-10-03T00:00:00Z' }; }
let pipeline: PipelineDefinition;
beforeEach(() => {
  jest.resetAllMocks(); pipeline = initial();
  useAuthStore.setState({ accessToken: 'test', sessionVersion: 0, user: { id: 'actor', org_id: org, email: 'a@example.org', role: 'org_admin' } });
  jest.mocked(api.get).mockImplementation(async url => {
    if (url === '/pipelines/' + id) return { data: pipeline } as never;
    return { data: { items: url === '/pipelines' ? [pipeline] : [], total: url === '/pipelines' ? 1 : 0, page: 1, per_page: 100, pages: url === '/pipelines' ? 1 : 0 } } as never;
  });
});
async function open(canManage = true, initialAction: 'view' | 'activation' = 'view') {
  const qc = createTestQueryClient();
  const onClose = jest.fn();
  render(<PipelineDefinitionDialog pipelineId={id} orgId={org} scope={scope} canManage={canManage} initialAction={initialAction} onClose={onClose} />, { wrapper: createWrapper(qc) });
  const dialog = await screen.findByRole('dialog');
  await within(dialog).findByText('Controlled pipeline');
  await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Перечитать состояние' })).toBeEnabled());
  return { dialog, qc, onClose };
}
function editName(dialog: HTMLElement) {
  fireEvent.click(within(dialog).getByRole('button', { name: 'Редактировать определение' }));
  fireEvent.change(within(dialog).getByLabelText('Название'), { target: { value: 'Edited pipeline' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Проверить изменения' }));
}
it('loads the owned definition and exposes params and links only in redacted overview', async () => {
  const { dialog } = await open();
  expect(api.get).toHaveBeenCalledWith('/pipelines/' + id, { signal: expect.any(AbortSignal) });
  expect(dialog.textContent).toContain('"on_success": null');
  expect(dialog.textContent).toContain('[скрыто]');
  expect(dialog.textContent).not.toContain('private-parameter');
  expect(api.patch).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
});
it('activation passes explicit desired state and inspected timestamp after confirmation', async () => {
  const { dialog } = await open(true, 'activation');
  jest.mocked(api.post).mockImplementation(async () => {
    pipeline = { ...pipeline, is_active: false, updated_at: '2026-10-03T00:01:00Z' };
    return { status: 200, data: pipeline } as never;
  });
  expect(api.post).not.toHaveBeenCalled();
  expect(within(dialog).getByText(/Действующие задания продолжатся/)).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить запись' }));
  await within(dialog).findByText(/Сохранение подтверждено API/);
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith(`/pipelines/${id}/toggle`, null, { params: { active: false, expected_updated_at: initial().updated_at } });
});
it('saves only changed fields and does not send a whole stale snapshot', async () => {
  const { dialog } = await open(); editName(dialog);
  expect(api.patch).not.toHaveBeenCalled();
  jest.mocked(api.patch).mockImplementation(async () => { pipeline = { ...pipeline, name: 'Edited pipeline', updated_at: '2026-10-03T00:01:00Z' }; return { status: 200, data: pipeline } as never; });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить запись' }));
  await within(dialog).findByText(/Сохранение подтверждено API/);
  expect(api.patch).toHaveBeenCalledWith('/pipelines/' + id, { name: 'Edited pipeline', expected_updated_at: initial().updated_at });
});
it.each([403, 404, 409, 422])('keeps draft and blocks repeat write after rejection %i', async status => {
  const { dialog } = await open(); editName(dialog);
  jest.mocked(api.patch).mockRejectedValue({ response: { status, data: { detail: 'private raw error' } } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить запись' }));
  await within(dialog).findByRole('alert');
  expect(within(dialog).getByLabelText('Название')).toHaveValue('Edited pipeline');
  expect(within(dialog).getByRole('button', { name: 'Проверить изменения' })).toBeDisabled();
  expect(api.patch).toHaveBeenCalledTimes(1); expect(dialog.textContent).not.toContain('private raw error');
});
it('unknown network outcome requires manual read and never automatic replay', async () => {
  const { dialog } = await open(); editName(dialog);
  jest.mocked(api.patch).mockRejectedValue(new Error('timeout'));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить запись' }));
  await within(dialog).findByText(/Результат записи неизвестен/);
  expect(within(dialog).getByRole('button', { name: 'Проверить изменения' })).toBeDisabled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Перечитать состояние' }));
  await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Проверить изменения' })).toBeEnabled());
  expect(api.patch).toHaveBeenCalledTimes(1);
});
it('a fresh read keeps dirty draft and rejects stale confirmation', async () => {
  const { dialog } = await open(); editName(dialog);
  pipeline = { ...pipeline, name: 'Competitor', updated_at: '2026-10-03T00:02:00Z' };
  fireEvent.click(within(dialog).getByRole('button', { name: 'Перечитать состояние' }));
  await within(dialog).findByText(/Серверное определение изменилось/);
  expect(within(dialog).getByLabelText('Название')).toHaveValue('Edited pipeline');
  expect(within(dialog).getByRole('button', { name: 'Проверить изменения' })).toBeDisabled();
  expect(within(dialog).queryByRole('button', { name: 'Подтвердить запись' })).not.toBeInTheDocument();
  expect(api.patch).not.toHaveBeenCalled();
});
it('requires explicit discard before closing an unsaved draft', async () => {
  const { dialog, onClose } = await open(); editName(dialog);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Закрыть' }));
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Сохранить черновик' }));
  expect(within(dialog).getByLabelText('Название')).toHaveValue('Edited pipeline');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Закрыть' }));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Да, отбросить' }));
  expect(onClose).toHaveBeenCalledTimes(1);
});
it('does not trust a wrong mutation receipt or announce success', async () => {
  const { dialog } = await open(); editName(dialog);
  jest.mocked(api.patch).mockResolvedValue({ status: 200, data: { ...pipeline, org_id: 'foreign' } } as never);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Подтвердить запись' }));
  await within(dialog).findByText(/Результат записи неизвестен/);
  expect(within(dialog).queryByText(/Сохранение подтверждено/)).not.toBeInTheDocument();
});
it('disallows double submission and close while write is in flight', async () => {
  const { dialog, onClose } = await open(); editName(dialog);
  let resolve!: (value: never) => void;
  jest.mocked(api.patch).mockReturnValue(new Promise(r => { resolve = r; }));
  const confirm = within(dialog).getByRole('button', { name: 'Подтвердить запись' });
  fireEvent.click(confirm); fireEvent.click(confirm);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Закрыть' }));
  expect(api.patch).toHaveBeenCalledTimes(1); expect(onClose).not.toHaveBeenCalled();
  await act(async () => resolve({ status: 200, data: { ...pipeline, name: 'Edited pipeline' } } as never));
});
it('viewer can inspect but cannot edit or activate', async () => {
  const { dialog } = await open(false);
  expect(within(dialog).getByRole('button', { name: 'Редактировать определение' })).toBeDisabled();
  expect(within(dialog).getByRole('button', { name: 'Выключить новые запуски' })).toBeDisabled();
});
it('failed read hides stale contents and disables writes', async () => {
  const { dialog } = await open();
  jest.mocked(api.get).mockRejectedValue(new Error('offline'));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Перечитать состояние' }));
  await within(dialog).findByText(/Не удалось получить достоверное определение/);
  expect(within(dialog).queryByRole('button', { name: 'Редактировать определение' })).not.toBeInTheDocument();
});
it.each(['steps', 'input_schema', 'tags'] as const)('invalid JSON %s never reaches API', async field => {
  const { dialog } = await open();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Редактировать определение' }));
  const label = { steps: 'Шаги JSON', input_schema: 'Входная схема JSON', tags: 'Теги JSON' }[field];
  fireEvent.change(within(dialog).getByLabelText(label), { target: { value: '{invalid' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Проверить изменения' }));
  await within(dialog).findByRole('alert'); expect(api.patch).not.toHaveBeenCalled();
});
it('catalog activation opens owned definition rather than firing a parameterless POST', async () => {
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  await screen.findByText('Controlled pipeline');
  fireEvent.click(screen.getByRole('button', { name: 'Деактивировать' }));
  const dialog = await screen.findByRole('dialog');
  await within(dialog).findByRole('button', { name: 'Подтвердить запись' });
  expect(api.post).not.toHaveBeenCalled();
});
it('retires an open definition on organization/session change', async () => {
  render(<OrchestrationPage />, { wrapper: createWrapper() });
  await screen.findByText('Controlled pipeline');
  fireEvent.click(screen.getByRole('button', { name: 'Определение и управление' }));
  await screen.findByRole('dialog');
  act(() => useAuthStore.setState({ sessionVersion: 1, user: { ...useAuthStore.getState().user!, org_id: 'other' } }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); expect(api.patch).not.toHaveBeenCalled();
});
it('null clear differs from omission and JSON key order does not create a false change', () => {
  const baseline = initial(); const draft = definitionDraft(baseline);
  expect(validateDefinitionDraft({ ...draft, description: '' }, baseline)).toEqual({ description: null });
  expect(canonical({ a: 1, b: 2 })).toEqual(canonical({ b: 2, a: 1 }));
  expect(validateDefinitionDraft(draft, baseline)).toEqual({});
});
