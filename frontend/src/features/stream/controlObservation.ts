import type { StreamFrameDimensions } from './streamAspectRatio';

export type AndroidControlCommand = { type: 'key_event'; keycode: number }
  | { type: 'type_text'; text: string };
export type StreamInput = {
  deviceId: string;
  /** Monotonic time at submission, never the time a late reply arrived. */
  at: number;
  dimensions: StreamFrameDimensions;
  command: AndroidControlCommand | { type: 'click'; x: number; y: number }
    | { type: 'swipe'; x1: number; y1: number; x2: number; y2: number; duration_ms: number };
};
export type AcknowledgedControl = { requestId: string; input: StreamInput } & (
  { phase: 'submitted' } | { phase: 'confirmed' | 'unknown'; completedAt: number }
);

export const ANDROID_EDIT_KEYCODES = new Set([3, 4, 187, 82, 67, 112, 66, 61, 278, 277, 279]);

/** Match the installed APK shell/input-text restrictions without changing text. */
export function androidTextCommand(text: string): string | null {
  if (!text || text.length > 1024 || /[^\x20-\x7e]/.test(text)
    || /[;|&$`(){}\\<>!#~']/.test(text) || text.includes('%s')) return null;
  return `input text '${text.replace(/ /g, '%s')}'`;
}
