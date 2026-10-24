/** Only an authenticated keyboard-capable control peer may carry this ephemeral payload. */
export type RemoteKeyboardCommand = { operation: 'commit' | 'compose'; editor_generation: number; text: string }
  | { operation: 'key_down' | 'key_up'; editor_generation: number; keycode: number; meta: number }
  | { operation: 'finish' | 'delete_backward' | 'delete_forward' | 'reset'; editor_generation: number };
export type RemoteKeyboardState = { enabled: boolean; editorGeneration: number; editorActive: boolean; reason: string };
export type RemoteKeyboardReceipt = { outcome: 'accepted'; receiptRoundTripMs: number }
  | { outcome: 'not_sent' | 'unknown' | 'no_editor' | 'stale_editor' | 'unavailable' | 'interrupted' };
export function validRemoteText(text: string): boolean {
  if (text.length > 1024 || /[\x00-\x08\x0b-\x1f]/.test(text)) return false;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) { const d = text.charCodeAt(++i); if (!(d >= 0xdc00 && d <= 0xdfff)) return false; }
    else if (c >= 0xdc00 && c <= 0xdfff) return false;
  }
  return true;
}
export const supportedHardwareKey = (code: unknown): code is number => typeof code === 'number' && Number.isInteger(code)
  && (code >= 7 && code <= 16 || code >= 29 && code <= 77 || code === 81 || code >= 113 && code <= 118
    || code === 124 || code >= 131 && code <= 164 || [3,4,187,82,67,112,66,61,19,20,21,22,23,111,122,123,92,93,278,277,279].includes(code));
export const supportedKeyMeta = (meta: unknown): meta is number => typeof meta === 'number' && Number.isInteger(meta)
  && meta >= 0 && meta <= 0x711003 && (meta & ~0x711003) === 0;
export function validKeyboardCommand(command: unknown): command is RemoteKeyboardCommand {
  if (!command || typeof command !== 'object' || Array.isArray(command)) return false;
  const c = command as Record<string, unknown>;
  if (!Number.isInteger(c.editor_generation) || (c.editor_generation as number) < 0 || (c.editor_generation as number) > 2147483647) return false;
  const base = 'editor_generation,operation';
  if (c.operation === 'commit' || c.operation === 'compose') return Object.keys(c).sort().join() === base + ',text'
    && typeof c.text === 'string' && validRemoteText(c.text) && (c.operation === 'compose' || c.text.length > 0);
  if (c.operation === 'key_down' || c.operation === 'key_up') return Object.keys(c).sort().join() === 'editor_generation,keycode,meta,operation'
    && supportedHardwareKey(c.keycode) && supportedKeyMeta(c.meta);
  return ['finish','delete_backward','delete_forward','reset'].includes(String(c.operation)) && Object.keys(c).sort().join() === base;
}
/** KeyboardEvent.code is physical; printable editor text is taken from beforeinput/IME instead. */
export function androidPhysicalKey(code: string): number | null {
  if (/^Key[A-Z]$/.test(code)) return 29 + code.charCodeAt(3) - 65;
  if (/^Digit[0-9]$/.test(code)) return 7 + Number(code[5]);
  if (/^Numpad[0-9]$/.test(code)) return 144 + Number(code[6]);
  if (/^F(?:[1-9]|1[0-2])$/.test(code)) return 130 + Number(code.slice(1));
  return ({ Enter:66, NumpadEnter:160, Space:62, Tab:61, Backspace:67, Delete:112,
    ArrowUp:19, ArrowDown:20, ArrowLeft:21, ArrowRight:22, Escape:111, Home:122, End:123,
    PageUp:92, PageDown:93, Insert:124, ShiftLeft:59, ShiftRight:60, AltLeft:57, AltRight:58,
    ControlLeft:113, ControlRight:114, MetaLeft:117, MetaRight:118, CapsLock:115, NumLock:143, ScrollLock:116,
    Comma:55, Period:56, Backquote:68, Minus:69, Equal:70, BracketLeft:71, BracketRight:72,
    Backslash:73, Semicolon:74, Quote:75, Slash:76, NumpadDivide:154, NumpadMultiply:155,
    NumpadSubtract:156, NumpadAdd:157, NumpadDecimal:158 })[code] ?? null;
}
