import { validPointerPath } from '@/lib/dag/pointerPath';
import type { DagNode } from '@/lib/dag/export';
import { ANDROID_EDIT_KEYCODES, androidTextCommand, type AcknowledgedControl, type StreamInput } from '@/src/features/stream/controlObservation';
import type { UiHierarchyNode, UiHierarchySnapshot } from '@/src/features/stream/uiHierarchy';
export type { StreamInput } from '@/src/features/stream/controlObservation';
type PlannedSelector = { deviceId: string; at: number; dimensions: { width: number; height: number };
  command: { type: 'tap_element'; selector: string; strategy: 'xpath'; timeout_ms: number };
  selectorSnapshot: { id: string; nodeId: number; rotation: number } };
export type RecordedInput = (StreamInput | PlannedSelector) & { id: string; requestId?: string; completedAt?: number;
  outcome: 'transport-submitted' | 'android-pending' | 'android-confirmed' | 'android-unknown' | 'selector-planned' };
export const RECORDING_LIMIT = 200;
export function appendRecording(entries: RecordedInput[], input: StreamInput, deviceId: string): RecordedInput[] {
  if (input.deviceId !== deviceId || !Number.isFinite(input.at) || ![input.dimensions.width, input.dimensions.height].every(value => Number.isInteger(value) && value >= 1 && value <= 16384)) throw new Error('Ввод относится к другому устройству или неверному кадру.');
  if (input.endedAt !== undefined && (!['click', 'swipe', 'pointer_path'].includes(input.command.type)
    || !Number.isFinite(input.endedAt) || input.endedAt < input.at)) throw new Error('Некорректное время завершения жеста.');
  if (entries.length >= RECORDING_LIMIT) throw new Error('Достигнут лимит записи: 200 действий. Остановите и перенесите запись.');
  if (!['click', 'swipe', 'pointer_path', 'key_event', 'type_text'].includes(input.command.type)) throw new Error('Неизвестный тип ввода.');
  if (entries.length && input.at < entries[entries.length - 1].at) throw new Error('Запись нарушает порядок времени.');
  const coords = input.command.type === 'click' ? [input.command.x, input.command.y] : input.command.type === 'swipe' ? [input.command.x1, input.command.y1, input.command.x2, input.command.y2] : [];
  if (coords.some((coord, index) => !Number.isInteger(coord) || coord < 0 || coord >= (index % 2 ? input.dimensions.height : input.dimensions.width))) throw new Error('Координаты записи вне кадра.');
  if (input.command.type === 'pointer_path' && (!validPointerPath(input.command.path)
    || input.command.path.frame_width !== input.dimensions.width || input.command.path.frame_height !== input.dimensions.height
    || input.endedAt === undefined || Math.round(input.endedAt-input.at) !== input.command.path.points.at(-1)!.t_ms))
    throw new Error('Неполная траектория касания или неверное время завершения.');
  if (input.command.type === 'swipe' && (!Number.isInteger(input.command.duration_ms) || input.command.duration_ms < 0 || input.command.duration_ms > 2147483647)) throw new Error('Некорректная длительность свайпа.');
  if (input.command.type === 'key_event' && !ANDROID_EDIT_KEYCODES.has(input.command.keycode)) throw new Error('Клавиша не поддерживается записью.');
  if (input.command.type === 'type_text' && !androidTextCommand(input.command.text)) throw new Error('Текст не поддерживается установленным каналом Android.');
  return [...entries, { ...input, dimensions: { ...input.dimensions }, command: JSON.parse(JSON.stringify(input.command)), id: crypto.randomUUID(), outcome: 'transport-submitted' }];
}
export function appendNativeRecording(entries: RecordedInput[], input: StreamInput, deviceId: string, requestId: string, completedAt: number): RecordedInput[] {
  if (!requestId || entries.some(entry => entry.requestId === requestId)
    || !['click','swipe','pointer_path'].includes(input.command.type) || !Number.isFinite(completedAt) || completedAt < (input.endedAt ?? input.at))
    throw new Error('Нативная запись не соответствует подтверждённому жесту.');
  const next = appendRecording(entries,input,deviceId);
  next[next.length-1] = {...next[next.length-1], requestId, completedAt, outcome:'android-confirmed'};
  return next;
}
/** Selecting a hierarchy node declares a future action; it never injects input.
 * Keep it in the same ordered review buffer instead of mutating the DAG early. */
export function appendSelectorRecording(entries: RecordedInput[], node: UiHierarchyNode, snapshot: UiHierarchySnapshot,
                                        deviceId: string, at: number): RecordedInput[] {
  if (entries.length >= RECORDING_LIMIT) throw new Error('Достигнут лимит записи: 200 действий. Остановите и перенесите запись.');
  if (snapshot.device_id !== deviceId || snapshot.source !== 'android_uiautomator_root'
    || !/^[a-f0-9]{32}$/.test(snapshot.snapshot_id) || !Number.isInteger(snapshot.rotation) || snapshot.rotation < 0 || snapshot.rotation > 3
    || ![snapshot.width, snapshot.height].every(value => Number.isInteger(value) && value >= 1 && value <= 16384)
    || !snapshot.nodes.some(value => value.id === node.id && value.xpath === node.xpath)
    || typeof node.xpath !== 'string' || node.xpath.length > 2048 || !/^\/hierarchy(?:\/node\[\d+\])+$/.test(node.xpath)) {
    throw new Error('XPath не принадлежит выбранному снимку Android или превышает лимит записи.');
  }
  if (!Number.isFinite(at) || entries.length && at < entries[entries.length - 1].at) throw new Error('Запись нарушает порядок времени.');
  return [...entries, { deviceId, at, dimensions: { width: snapshot.width, height: snapshot.height }, id: crypto.randomUUID(),
    command: { type: 'tap_element', selector: node.xpath, strategy: 'xpath', timeout_ms: 5000 },
    selectorSnapshot: { id: snapshot.snapshot_id, nodeId: node.id, rotation: snapshot.rotation }, outcome: 'selector-planned' }];
}
/** Keep response updates in the original submission slot, including after Stop.
 * A late/foreign response cannot append an action or confirm another command. */
export function observeAcknowledgedRecording(entries: RecordedInput[], event: AcknowledgedControl, deviceId: string, recording: boolean): RecordedInput[] {
  if (event.input.deviceId !== deviceId || !event.requestId || !['key_event', 'type_text'].includes(event.input.command.type)) return entries;
  if (event.phase === 'submitted') {
    if (!recording || entries.some(entry => entry.requestId === event.requestId)) return entries;
    const next = appendRecording(entries, event.input, deviceId);
    next[next.length - 1] = { ...next[next.length - 1], requestId: event.requestId, outcome: 'android-pending' };
    return next;
  }
  const index = entries.findIndex(entry => entry.requestId === event.requestId);
  if (index < 0 || entries[index].outcome !== 'android-pending') return entries;
  const entry = entries[index];
  if (!Number.isFinite(event.completedAt) || event.completedAt < entry.at
    || event.input.at !== entry.at || event.input.dimensions.width !== entry.dimensions.width
    || event.input.dimensions.height !== entry.dimensions.height
    || JSON.stringify(event.input.command) !== JSON.stringify(entry.command)) return entries;
  return entries.map((value, position) => position === index
    ? { ...value, completedAt: event.completedAt, outcome: event.phase === 'confirmed' ? 'android-confirmed' : 'android-unknown' } : value);
}
/** The agent DAG uses a 720×1280 reference coordinate system. The display
 * orientation is captured per gesture; stream coordinates never become raw taps. */
export function recordedAction(input: RecordedInput): DagNode['action'] {
  const landscape = input.dimensions.width > input.dimensions.height;
  const width = landscape ? 1280 : 720, height = landscape ? 720 : 1280;
  const x = (coord: number) => Math.min(width - 1, Math.floor(coord * width / input.dimensions.width));
  const y = (coord: number) => Math.min(height - 1, Math.floor(coord * height / input.dimensions.height));
  const command = input.command;
  if (input.outcome === 'android-pending' || input.outcome === 'android-unknown') throw new Error('У команды Android нет подтверждённого результата. Дождитесь ответа или удалите этот шаг после проверки экрана.');
  if (command.type === 'tap_element') {
    if (input.outcome !== 'selector-planned') throw new Error('XPath не подтверждён как явно выбранный будущий шаг.');
    return { ...command };
  }
  if (command.type === 'key_event' || command.type === 'type_text') {
    if (input.outcome !== 'android-confirmed') throw new Error('Команда Android не подтверждена.');
    return command.type === 'key_event' ? { type: 'key_event', keycode: command.keycode }
      : { type: 'type_text', text: command.text, clear_first: false };
  }
  if (command.type === 'pointer_path') {
    if (input.outcome !== 'android-confirmed') throw new Error('Границы жеста не подтверждены Android.');
    return {type:'pointer_path',path:JSON.parse(JSON.stringify(command.path))};
  }
  return command.type === 'click' ? { type: 'tap', x: x(command.x), y: y(command.y) }
    : { type: 'swipe', x1: x(command.x1), y1: y(command.y1), x2: x(command.x2), y2: y(command.y2), duration_ms: command.duration_ms };
}
export function recordingActions(entries: RecordedInput[], preservePauses = true): DagNode['action'][] {
  const actions: DagNode['action'][] = [];
  for (let index = 0; index < entries.length; index++) {
    if (index) {
      const previous = entries[index - 1];
      if (previous.deviceId !== entries[index].deviceId || entries[index].at < previous.at) throw new Error('Запись смешивает устройства или нарушает порядок времени.');
      // Pointer pauses start at local UP, not its later ACK. Key/text steps
      // await execution themselves; overlap does not create a negative pause.
      const previousEnd = ('endedAt' in previous ? previous.endedAt : undefined) ?? previous.completedAt ?? previous.at + (previous.command.type === 'swipe' ? previous.command.duration_ms : 0);
      const gap = Math.max(0, Math.round(entries[index].at - previousEnd));
      if (preservePauses && gap > 0) actions.push({ type: 'sleep', ms: Math.min(60000, gap) });
    }
    actions.push(recordedAction(entries[index]));
  }
  return actions;
}
