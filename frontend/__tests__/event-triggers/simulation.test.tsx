import { act, fireEvent, render, screen, within } from '@testing-library/react';
import EventTriggersPage from '@/app/(dashboard)/event-triggers/page';
import { api } from '@/lib/api';
import type { TriggerSimulationResult } from '@/lib/hooks/useEventTriggers';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
let mockCanReadEvents = false;
jest.mock('@/src/features/access/Capabilities', () => ({
  useCapabilities: () => ({ can: (permission: string) => permission === 'pipeline:read' || (permission === 'event:read' && mockCanReadEvents) }),
  PermissionNotice: () => null,
}));

const trigger = {
  id: 'trigger-a', name: 'Сбой сценария', is_active: true, total_triggers: 4,
  event_type_pattern: 'task.*', pipeline_id: 'pipe-a', cooldown_seconds: 60, max_triggers_per_hour: 3,
};
const observedAt = '2026-11-13T21:00:00Z';
const retryAt = '2026-11-13T21:25:00Z';
const result: TriggerSimulationResult = {
  trigger_id: trigger.id,
  event_type: 'task.failed',
  matches: true,
  would_admit: false,
  reason: 'hour_limit',
  observed_at: observedAt,
  retry_at: retryAt,
  recent_runs: 3,
  max_triggers_per_hour: 3,
};

function respondToSimulation(respond: () => Promise<{ data: TriggerSimulationResult }>) {
  jest.mocked(api.get).mockImplementation(async (url) => {
    if (url === '/event-triggers') return { data: { items: [trigger], total: 1 } };
    if (url === '/pipelines') return { data: { items: [], total: 0 } };
    return respond();
  });
}

async function openSimulation() {
  render(<EventTriggersPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Проверить условия триггера Сбой сценария' }));
  const dialog = within(await screen.findByRole('dialog'));
  return { dialog, input: dialog.getByLabelText('Тип события') };
}

beforeEach(() => {
  jest.resetAllMocks();
  mockCanReadEvents = false;
});

it('uses a saved event to explain duplicate and causal limits without creating a run', async () => {
  mockCanReadEvents = true;
  const eventId = '7e9c8df1-48a7-4a4f-9e11-a26000230000';
  const rootId = '7e9c8df1-48a7-4a4f-9e11-a26000240000';
  respondToSimulation(async () => ({ data: {
    ...result, event_id: eventId, event_origin: 'pipeline', root_event_id: rootId,
    reason: 'causal_cycle', retry_at: null, cause_depth: 2, max_cause_depth: 8, root_runs: 2, max_root_runs: 32,
  } }));
  const { dialog } = await openSimulation();
  fireEvent.change(dialog.getByLabelText('Источник проверки'), { target: { value: 'saved' } });
  const idInput = dialog.getByLabelText('ID события');
  fireEvent.change(idInput, { target: { value: 'not-an-id' } });
  expect(dialog.getByRole('button', { name: 'Проверить' })).toBeDisabled();
  fireEvent.change(idInput, { target: { value: eventId.toUpperCase() } });
  fireEvent.click(dialog.getByRole('button', { name: 'Проверить' }));
  expect(await dialog.findByText('Правило уже срабатывало в этой цепочке')).toBeInTheDocument();
  expect(dialog.getByText('Пайплайн', { exact: true })).toBeInTheDocument();
  expect(dialog.getByText(rootId)).toBeInTheDocument();
  expect(dialog.getByText('2 / 8')).toBeInTheDocument();
  expect(dialog.getByText('2 / 32')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/event-triggers/trigger-a/simulate', { params: { event_id: eventId } });
  expect(api.post).not.toHaveBeenCalled();
});

it('runs a read-only check under pipeline:read and reports match, rolling budget and the next eligible time', async () => {
  respondToSimulation(async () => ({ data: result }));
  const { dialog, input } = await openSimulation();
  expect(screen.queryByRole('button', { name: 'Создать триггер' })).not.toBeInTheDocument();
  expect(dialog.queryByLabelText('Источник проверки')).not.toBeInTheDocument();
  expect(dialog.getByRole('button', { name: 'Проверить' })).toBeDisabled();
  expect(dialog.getByText(/Пайплайн не запускается/)).toBeInTheDocument();
  fireEvent.change(input, { target: { value: ' task.failed ' } });
  fireEvent.click(dialog.getByRole('button', { name: 'Проверить' }));
  expect(await dialog.findByText('Исчерпан лимит за последние 60 минут')).toBeInTheDocument();
  expect(dialog.getByText('Да')).toBeInTheDocument();
  expect(dialog.getByText('3 / 3')).toBeInTheDocument();
  expect(dialog.getAllByRole('time').map(element => element.getAttribute('datetime'))).toEqual([observedAt, retryAt]);
  expect(api.get).toHaveBeenCalledWith('/event-triggers/trigger-a/simulate', { params: { event_type: 'task.failed' } });
  expect(api.post).not.toHaveBeenCalled();
  expect(api.patch).not.toHaveBeenCalled();
  expect(api.delete).not.toHaveBeenCalled();
});

it('disables repeat while pending and retires the old result when the sample changes', async () => {
  let resolveResponse: (value: { data: TriggerSimulationResult }) => void = () => {};
  respondToSimulation(() => new Promise(resolve => { resolveResponse = resolve; }));
  const { dialog, input } = await openSimulation();
  fireEvent.change(input, { target: { value: 'task.failed' } });
  fireEvent.click(dialog.getByRole('button', { name: 'Проверить' }));
  expect(await dialog.findByRole('button', { name: 'Проверяем…' })).toBeDisabled();
  expect(input).toBeDisabled();
  await act(async () => resolveResponse({ data: result }));
  expect(await dialog.findByText('Исчерпан лимит за последние 60 минут')).toBeInTheDocument();
  fireEvent.change(input, { target: { value: 'task.completed' } });
  expect(dialog.queryByText('Исчерпан лимит за последние 60 минут')).not.toBeInTheDocument();
});

it('fails closed on a receipt for a different trigger and allows an explicit retry', async () => {
  let attempts = 0;
  respondToSimulation(async () => ({ data: attempts++ ? result : { ...result, trigger_id: 'another-trigger' } }));
  const { dialog, input } = await openSimulation();
  fireEvent.change(input, { target: { value: 'task.failed' } });
  fireEvent.click(dialog.getByRole('button', { name: 'Проверить' }));
  expect(await dialog.findByRole('alert')).toHaveTextContent('Результат проверки не подтверждён.');
  expect(dialog.queryByText('Исчерпан лимит за последние 60 минут')).not.toBeInTheDocument();
  fireEvent.click(dialog.getByRole('button', { name: 'Проверить' }));
  expect(await dialog.findByText('Исчерпан лимит за последние 60 минут')).toBeInTheDocument();
  expect(attempts).toBe(2);
});

it.each([
  ['eligible', 'Условия допуска выполнены'],
  ['pattern_mismatch', 'Тип события не совпадает с шаблоном'],
  ['trigger_disabled', 'Триггер отключён'],
  ['pipeline_unavailable', 'Пайплайн недоступен'],
  ['cooldown', 'Действует пауза между запусками'],
] as const)('presents the %s decision without offering a launch', async (reason, label) => {
  respondToSimulation(async () => ({
    data: {
      ...result, reason, matches: reason !== 'pattern_mismatch', would_admit: reason === 'eligible',
      retry_at: reason === 'cooldown' ? retryAt : null,
    },
  }));
  const { dialog, input } = await openSimulation();
  fireEvent.change(input, { target: { value: 'task.failed' } });
  fireEvent.click(dialog.getByRole('button', { name: 'Проверить' }));
  expect(await dialog.findByText(label)).toBeInTheDocument();
  expect(dialog.queryByRole('button', { name: /Запустить/ })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});
