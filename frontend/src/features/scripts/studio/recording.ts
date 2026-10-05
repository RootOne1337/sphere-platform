import type { StreamFrameDimensions } from '@/src/features/stream/streamAspectRatio';
import type { DagNode } from '@/lib/dag/export';
export type StreamInput = { deviceId: string; at: number; dimensions: StreamFrameDimensions; command:
  { type: 'click'; x: number; y: number } | { type: 'swipe'; x1: number; y1: number; x2: number; y2: number; duration_ms: number } };
export type RecordedInput = StreamInput & { id: string; outcome: 'transport-submitted' };
export const RECORDING_LIMIT = 200;
export function appendRecording(entries: RecordedInput[], input: StreamInput, deviceId: string): RecordedInput[] {
  if (input.deviceId !== deviceId || !Number.isFinite(input.at) || ![input.dimensions.width, input.dimensions.height].every(value => Number.isInteger(value) && value >= 1 && value <= 16384)) throw new Error('Ввод относится к другому устройству или неверному кадру.');
  if (entries.length >= RECORDING_LIMIT) throw new Error('Достигнут лимит записи: 200 действий. Остановите и перенесите запись.');
  const coords = input.command.type === 'click' ? [input.command.x, input.command.y] : [input.command.x1, input.command.y1, input.command.x2, input.command.y2];
  if (coords.some((coord, index) => !Number.isInteger(coord) || coord < 0 || coord >= (index % 2 ? input.dimensions.height : input.dimensions.width))) throw new Error('Координаты записи вне кадра.');
  if (input.command.type === 'swipe' && (!Number.isInteger(input.command.duration_ms) || input.command.duration_ms < 0 || input.command.duration_ms > 2147483647)) throw new Error('Некорректная длительность свайпа.');
  return [...entries, { ...input, dimensions: { ...input.dimensions }, command: { ...input.command }, id: crypto.randomUUID(), outcome: 'transport-submitted' }];
}
/** The agent DAG uses a 720×1280 reference coordinate system. The display
 * orientation is captured per gesture; stream coordinates never become raw taps. */
export function recordedAction(input: RecordedInput): DagNode['action'] {
  const landscape = input.dimensions.width > input.dimensions.height;
  const width = landscape ? 1280 : 720, height = landscape ? 720 : 1280;
  const x = (coord: number) => Math.min(width - 1, Math.floor(coord * width / input.dimensions.width));
  const y = (coord: number) => Math.min(height - 1, Math.floor(coord * height / input.dimensions.height));
  const command = input.command;
  return command.type === 'click' ? { type: 'tap', x: x(command.x), y: y(command.y) }
    : { type: 'swipe', x1: x(command.x1), y1: y(command.y1), x2: x(command.x2), y2: y(command.y2), duration_ms: command.duration_ms };
}
export function recordingActions(entries: RecordedInput[], preservePauses = true): DagNode['action'][] {
  const actions: DagNode['action'][] = [];
  for (let index = 0; index < entries.length; index++) {
    if (index) {
      const previous = entries[index - 1];
      if (previous.deviceId !== entries[index].deviceId || entries[index].at < previous.at) throw new Error('Запись смешивает устройства или нарушает порядок времени.');
      const gap = Math.max(0, Math.round(entries[index].at - previous.at) - (previous.command.type === 'swipe' ? previous.command.duration_ms : 0));
      if (preservePauses && gap >= 100) actions.push({ type: 'sleep', ms: Math.min(60000, gap) });
    }
    actions.push(recordedAction(entries[index]));
  }
  return actions;
}
