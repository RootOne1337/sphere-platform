import { useState } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { deserialize, serialize } from 'node:v8';
import { NodeInspector } from '@/src/features/scripts/studio/NodeInspector';
import { appendRecording, recordedAction, recordingActions, RECORDING_LIMIT, type RecordedInput, type StreamInput } from '@/src/features/scripts/studio/recording';
import type { DagNode } from '@/lib/dag/export';
import { layoutWorkflow } from '@/src/features/scripts/studio/layout';
import type { Edge, Node } from '@xyflow/react';

const mockLayout = jest.fn();
const mockElkConstructor = jest.fn();
jest.mock('elkjs/lib/elk-api', () => ({ __esModule: true, default: jest.fn().mockImplementation(() => {
  mockElkConstructor();
  return { layout: mockLayout };
}) }));

// jsdom exposes neither the browser clone primitive nor crypto.randomUUID.
beforeAll(() => {
  Object.defineProperty(globalThis, 'structuredClone', { configurable: true, value: (value: unknown) => deserialize(serialize(value)) });
  Object.defineProperty(globalThis.crypto, 'randomUUID', { configurable: true, value: () => '00000000-0000-4000-8000-000000000001' });
});

const deviceId = 'b410464a-5f26-4803-a756-7840cc17b128';
function input(overrides: Partial<StreamInput> = {}): StreamInput {
  return { deviceId, at: 1234, dimensions: { width: 960, height: 540 }, command: { type: 'click', x: 480, y: 270 }, ...overrides };
}
function recorded(value: StreamInput): RecordedInput { return appendRecording([], value, deviceId)[0]; }

describe('recorded Android input contract', () => {
  it('normalizes a 540p landscape frame into the installed APK 1280×720 DAG reference', () => {
    expect(recordedAction(recorded(input()))).toEqual({ type: 'tap', x: 640, y: 360 });
    expect(recordedAction(recorded(input({ command: { type: 'click', x: 959, y: 539 } })))).toEqual({ type: 'tap', x: 1278, y: 718 });
  });
  it('uses the portrait 720×1280 reference for both endpoints of a gesture', () => {
    const value = input({ dimensions: { width: 540, height: 960 }, command: { type: 'swipe', x1: 270, y1: 720, x2: 270, y2: 240, duration_ms: 360 } });
    expect(recordedAction(recorded(value))).toEqual({ type: 'swipe', x1: 360, y1: 960, x2: 360, y2: 320, duration_ms: 360 });
  });
  it('records transport submission without inventing an Android execution acknowledgement', () => {
    expect(recorded(input()).outcome).toBe('transport-submitted');
    expect(recorded(input())).not.toHaveProperty('confirmed');
    expect(recorded(input())).not.toHaveProperty('success');
  });
  it('copies the observed input so later decoder or pointer mutations cannot rewrite the recording', () => {
    const value = input();
    const entries = appendRecording([], value, deviceId);
    value.dimensions.width = 12;
    if (value.command.type === 'click') value.command.x = 1;
    expect(entries[0].dimensions.width).toBe(960);
    expect(entries[0].command).toEqual({ type: 'click', x: 480, y: 270 });
  });
  it('rejects a gesture from another selected device and preserves the existing recording', () => {
    const entries = appendRecording([], input(), deviceId);
    expect(() => appendRecording(entries, input({ deviceId: 'another-device' }), deviceId)).toThrow();
    expect(entries).toHaveLength(1);
  });
  it.each([
    { width: 0, height: 540 }, { width: 960, height: 0 },
    { width: Number.NaN, height: 540 }, { width: Number.POSITIVE_INFINITY, height: 540 },
    { width: 960.5, height: 540 }, { width: 960, height: 16_385 },
  ])('rejects invalid or unbounded capture dimensions %j', dimensions => {
    expect(() => appendRecording([], input({ dimensions }), deviceId)).toThrow();
  });
  it.each([
    { type: 'click' as const, x: -1, y: 20 }, { type: 'click' as const, x: 960, y: 20 },
    { type: 'click' as const, x: 20, y: 540 }, { type: 'click' as const, x: 0.25, y: 0 },
    { type: 'swipe' as const, x1: 0, y1: 0, x2: 960, y2: 10, duration_ms: 300 },
  ])('rejects coordinates outside the owned frame %j', command => {
    expect(() => appendRecording([], input({ command }), deviceId)).toThrow();
  });
  it.each([Number.NaN, Number.POSITIVE_INFINITY, -1, 1.5])('rejects an invalid recorded swipe duration %s', duration_ms => {
    expect(() => appendRecording([], input({ command: { type: 'swipe', x1: 20, y1: 30, x2: 40, y2: 50, duration_ms } }), deviceId)).toThrow();
  });
  it('bounds a session to 200 actions instead of dropping old evidence or allocating indefinitely', () => {
    const entry = recorded(input());
    const previous = Array.from({ length: RECORDING_LIMIT - 1 }, (_, index) => ({ ...entry, id: String(index) }));
    const full = appendRecording(previous, input(), deviceId);
    expect(full).toHaveLength(200);
    expect(previous).toHaveLength(199);
    expect(() => appendRecording(full, input(), deviceId)).toThrow('200');
    expect(full[0].id).toBe('0');
  });
  it('preserves navigation pauses by default and subtracts the preceding swipe duration', () => {
    const first = recorded(input({ at: 1000, command: { type: 'swipe', x1: 480, y1: 400, x2: 480, y2: 100, duration_ms: 350 } }));
    const second = recorded(input({ at: 2000 }));
    expect(recordingActions([first, second])).toEqual([
      recordedAction(first), { type: 'sleep', ms: 650 }, recordedAction(second),
    ]);
  });
  it('caps a recorded long pause at 60 seconds and lets explicit pause opt-out omit only wait actions', () => {
    const first = recorded(input({ at: 1000 }));
    const second = recorded(input({ at: 200_000 }));
    expect(recordingActions([first, second])).toEqual([recordedAction(first), { type: 'sleep', ms: 60_000 }, recordedAction(second)]);
    expect(recordingActions([first, second], false)).toEqual([recordedAction(first), recordedAction(second)]);
  });
  it.each([true, false])('rejects mixed devices even when preserving pauses is %s', preservePauses => {
    const first = recorded(input({ at: 1000 }));
    const second = { ...recorded(input({ at: 2000 })), deviceId: 'foreign-device' };
    expect(() => recordingActions([first, second], preservePauses)).toThrow();
  });
  it.each([true, false])('rejects a nonmonotonic recording even when preserving pauses is %s', preservePauses => {
    expect(() => recordingActions([recorded(input({ at: 2000 })), recorded(input({ at: 1000 }))], preservePauses)).toThrow();
  });
});

function InspectorHarness({ node, changed, writable = true }: { node: DagNode; changed: (source: string) => void; writable?: boolean }) {
  const [source, setSource] = useState(JSON.stringify(node));
  return <NodeInspector source={source} onChange={next => { setSource(next); changed(next); }} nodes={[{ id: 'one' }, { id: 'end' }]} writable={writable} pending apply={jest.fn()} cancel={jest.fn()} />;
}
function renderNode(action: DagNode['action'], extra: Partial<DagNode> = {}, writable = true) {
  const node: DagNode = { id: 'one', action, on_success: 'end', ...extra };
  const changed = jest.fn();
  render(<InspectorHarness node={node} changed={changed} writable={writable} />);
  return { node, changed, latest: () => JSON.parse(changed.mock.calls.at(-1)![0]) as DagNode };
}

describe('structured Studio parameters match the APK action vocabulary', () => {
  it('adds an optional runtime parameter only after an explicit choice and keeps the source unchanged before that', () => {
    const { node, changed, latest } = renderNode({ type: 'tap_element', selector: 'OK', strategy: 'text' });
    const optional = screen.getByRole('combobox', { name: 'Дополнительный параметр действия' });
    expect(within(optional).getByRole('option', { name: /fail_if_not_found/ })).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
    fireEvent.change(optional, { target: { value: 'fail_if_not_found' } });
    expect(changed).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Добавить параметр' }));
    expect(latest().action.fail_if_not_found).toBe(true);
    expect(node.action).not.toHaveProperty('fail_if_not_found');
  });
  it('offers result storage only to actual save_to handlers and never materializes a default automatically', () => {
    const first = renderNode({ type: 'screenshot' });
    const optional = screen.getByRole('combobox', { name: 'Дополнительный параметр действия' });
    expect(within(optional).getByRole('option', { name: /save_to/ })).toBeInTheDocument();
    expect(first.changed).not.toHaveBeenCalled();
  });
  it('does not offer save_to for an input_clear handler that ignores it', () => {
    renderNode({ type: 'input_clear' });
    expect(screen.queryByRole('combobox', { name: 'Дополнительный параметр действия' })).not.toBeInTheDocument();
  });
  it('offers content-desc through the installed desc strategy, not an unsupported description alias', () => {
    const { latest } = renderNode({ type: 'tap_element', selector: 'Settings', strategy: 'xpath' });
    const strategy = screen.getByLabelText(/Стратегия поиска/);
    expect(within(strategy).getByRole('option', { name: 'desc' })).toBeInTheDocument();
    expect(within(strategy).queryByRole('option', { name: 'description' })).not.toBeInTheDocument();
    fireEvent.change(strategy, { target: { value: 'desc' } });
    expect(latest().action).toMatchObject({ strategy: 'desc', selector: 'Settings' });
  });
  it('keeps condition and assertion checks distinct instead of offering battery_above to assert', () => {
    renderNode({ type: 'assert', check: 'element_exists', params: { selector: 'Settings', strategy: 'text' } });
    const check = screen.getByLabelText(/Тип проверки/);
    expect(within(check).queryByRole('option', { name: 'battery_above' })).not.toBeInTheDocument();
    for (const name of ['element_exists', 'element_gone', 'text_equals', 'text_contains', 'variable_equals', 'variable_contains', 'http_status']) {
      expect(within(check).getByRole('option', { name })).toBeInTheDocument();
    }
  });
  it('creates a missing params object when an explicitly edited template field is applied', () => {
    const { node, latest } = renderNode({ type: 'assert', check: 'element_exists' });
    fireEvent.change(screen.getByLabelText(/Селектор элемента/), { target: { value: '//*[@text="Settings"]' } });
    expect(latest().action.params).toMatchObject({ selector: '//*[@text="Settings"]' });
    expect(node.action).not.toHaveProperty('params');
  });
  it('loads a variable assertion without params using key/value fields without silently materializing defaults', () => {
    const { node, changed, latest } = renderNode({ type: 'assert', check: 'variable_equals' });
    expect(screen.getByLabelText(/Имя переменной/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Значение/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Селектор элемента/)).not.toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Имя переменной/), { target: { value: 'score' } });
    expect(latest().action.params).toEqual({ key: 'score' });
    expect(node.action).not.toHaveProperty('params');
  });
  it('fills only display gaps for the imported check while preserving custom strategy and exact supplied value types', () => {
    const existing = { strategy: 'vendor-strategy', key: 'counter', value: 0, custom: [false, null, '02'] };
    const { changed, latest } = renderNode({ type: 'assert', check: 'variable_equals', params: existing });
    expect(screen.getByLabelText(/Значение/)).toHaveAttribute('type', 'number');
    expect(within(screen.getByLabelText(/Стратегия поиска/)).getByRole('option', { name: 'vendor-strategy' })).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Повторы|retry/), { target: { value: '2' } });
    expect(latest().action.params).toEqual(existing);
  });
  it('displays the missing assert text_contains value without offering the condition text field', () => {
    const { changed } = renderNode({ type: 'assert', check: 'text_contains', params: { selector: 'Settings', strategy: 'text' } });
    expect(screen.getByLabelText(/Значение/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Текст text/)).not.toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
  });
  it('changes assertion parameter shape explicitly when switching from an element check to a variable check', () => {
    const { latest } = renderNode({ type: 'assert', check: 'element_exists', params: { selector: 'Settings', strategy: 'text', timeout_ms: 5000 } });
    fireEvent.change(screen.getByLabelText(/Тип проверки/), { target: { value: 'variable_equals' } });
    expect(latest().action.check).toBe('variable_equals');
    expect(latest().action.params).toHaveProperty('key');
    expect(latest().action.params).toHaveProperty('value');
    expect(latest().action.params).not.toHaveProperty('selector');
    expect(latest().action.params).not.toHaveProperty('strategy');
  });
  it.each(['text_equals', 'text_contains'])('uses params.value for the installed assert %s executor', check => {
    const { latest } = renderNode({ type: 'assert', check: 'element_exists', params: { selector: 'Settings', strategy: 'text' } });
    fireEvent.change(screen.getByLabelText(/Тип проверки/), { target: { value: check } });
    expect(latest().action.params).toHaveProperty('selector');
    expect(latest().action.params).toHaveProperty('value');
    expect(latest().action.params).not.toHaveProperty('text');
  });
  it('uses a node reference and numeric expected value for the installed HTTP assertion executor', () => {
    const { latest } = renderNode({ type: 'assert', check: 'element_exists', params: { selector: 'Settings', strategy: 'text' } });
    fireEvent.change(screen.getByLabelText(/Тип проверки/), { target: { value: 'http_status' } });
    expect(latest().action.params).toEqual({ node_id: '', value: 200 });
  });
  it('preserves exact JSON types, unknown attributes and routes through unrelated structured edits', () => {
    const preserved = { headers: { 'X-Count': '003' }, custom: { enabled: false, count: 0, nested: [null, true, '02', 2] } };
    const { node, latest } = renderNode({ type: 'http_request', url: 'https://example.com', method: 'POST', ...preserved }, { on_failure: 'one', retry: 1, timeout_ms: 2000 });
    fireEvent.change(screen.getByLabelText(/Повторы|retry/), { target: { value: '2' } });
    expect(latest()).toMatchObject({ id: 'one', on_success: 'end', on_failure: 'one', retry: 2, timeout_ms: 2000, action: preserved });
    expect(node.retry).toBe(1);
    expect(latest().action).not.toHaveProperty('body'); // Display templates are not silently saved.
  });
  it('preserves unknown imported strategy options instead of silently rewriting the source', () => {
    const { changed } = renderNode({ type: 'tap_element', selector: 'target', strategy: 'vendor-strategy' });
    expect(within(screen.getByLabelText(/Стратегия поиска/)).getByRole('option', { name: 'vendor-strategy' })).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
  });
  it('does not expose structured mutation controls as writable to a read-only operator', () => {
    const { changed } = renderNode({ type: 'tap_element', selector: 'target', strategy: 'xpath' }, {}, false);
    expect(screen.getByLabelText(/Стратегия поиска/)).toBeDisabled();
    expect(screen.getByLabelText(/Селектор элемента/)).toHaveAttribute('readonly');
    expect(screen.getByRole('button', { name: 'Применить параметры' })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Дополнительный параметр действия' })).toBeDisabled();
    expect(changed).not.toHaveBeenCalled();
  });
});

describe('ELK worker ownership and bounded lifetime', () => {
  const nodes: Node[] = [
    { id: 'one', position: { x: 10, y: 20 }, type: 'Start', data: { action: { type: 'start' }, custom: { revision: 7 } } },
    { id: 'end', position: { x: 30, y: 40 }, type: 'End', data: { action: { type: 'end' } } },
  ];
  const edges: Edge[] = [{ id: 'one-end', source: 'one', target: 'end', sourceHandle: null }];
  let terminate: jest.Mock;
  let worker: jest.Mock;
  const previousWorker = globalThis.Worker;
  beforeEach(() => {
    jest.useFakeTimers();
    mockLayout.mockReset(); mockElkConstructor.mockReset();
    terminate = jest.fn();
    worker = jest.fn().mockImplementation(() => ({ terminate }));
    Object.defineProperty(globalThis, 'Worker', { configurable: true, value: worker });
  });
  afterEach(() => {
    jest.useRealTimers();
    Object.defineProperty(globalThis, 'Worker', { configurable: true, value: previousWorker });
  });
  async function started() { for (let tick = 0; tick < 4; tick++) await Promise.resolve(); }
  it('changes only positions and releases the request-owned local worker after success', async () => {
    mockLayout.mockResolvedValue({ children: [{ id: 'one', x: 1, y: 2 }, { id: 'end', x: 300, y: 2 }] });
    const result = await layoutWorkflow(nodes, edges, new AbortController().signal);
    expect(result.map(node => node.position)).toEqual([{ x: 1, y: 2 }, { x: 300, y: 2 }]);
    expect(result[0].data).toEqual(nodes[0].data);
    expect(nodes[0].position).toEqual({ x: 10, y: 20 });
    expect(edges[0].sourceHandle).toBeNull();
    expect(worker).toHaveBeenCalledWith('/vendor/elk/worker-0.12.0.js');
    expect(terminate).toHaveBeenCalledTimes(1);
    expect(jest.getTimerCount()).toBe(0);
  });
  it('terminates a pending worker immediately when its owner cancels the layout', async () => {
    mockLayout.mockReturnValue(new Promise(() => {}));
    const controller = new AbortController();
    const request = layoutWorkflow(nodes, edges, controller.signal);
    const rejected = expect(request).rejects.toThrow('отменена');
    await started(); controller.abort(); await rejected;
    expect(terminate).toHaveBeenCalledTimes(1);
    expect(jest.getTimerCount()).toBe(0);
  });
  it('terminates an unresponsive worker at the ten-second budget without mutating the graph', async () => {
    mockLayout.mockReturnValue(new Promise(() => {}));
    const request = layoutWorkflow(nodes, edges, new AbortController().signal);
    const rejected = expect(request).rejects.toThrow('10 секунд');
    await started(); jest.advanceTimersByTime(10_000); await rejected;
    expect(terminate).toHaveBeenCalledTimes(1);
    expect(nodes[1].position).toEqual({ x: 30, y: 40 });
  });
  it('releases the worker even if ELK initialization fails before layout can start', async () => {
    mockElkConstructor.mockImplementation(() => { throw new Error('ELK init failed'); });
    await expect(layoutWorkflow(nodes, edges, new AbortController().signal)).rejects.toThrow('ELK init failed');
    expect(terminate).toHaveBeenCalledTimes(1);
    expect(mockLayout).not.toHaveBeenCalled();
  });
});
