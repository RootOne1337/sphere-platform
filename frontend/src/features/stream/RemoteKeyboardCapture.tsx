'use client';
import { useEffect, useRef, useState } from 'react';
import { Keyboard } from 'lucide-react';
import type { ContinuousPointer } from './continuousPointer';
import { androidPhysicalKey, validRemoteText, type RemoteKeyboardCommand } from './remoteKeyboardProtocol';

/** Focused remote input only. No global typing/clipboard listeners and no reconnect replay. */
export function RemoteKeyboardCapture({ controller, available, viewport }: {
  controller: () => ContinuousPointer | null; available: boolean; viewport: React.RefObject<HTMLElement | null>;
}) {
  const callbacks = useRef({ controller, available }); callbacks.current = { controller, available };
  const textarea = useRef<HTMLTextAreaElement>(null);
  const [wanted, setWanted] = useState(false), [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wantedRef = useRef(false);
  const cleanupRef = useRef<() => void>(() => {});
  useEffect(() => {
    const input = textarea.current;
    if (!input) return;
    let current: ContinuousPointer | null = null, composing = false, lastCompositionInsert: string | null = null, disposed = false;
    const held = new Map<string, number>();
    const errors = { not_sent:'Ввод не отправлен: канал управления ещё не готов.', unknown:'Результат ввода не подтверждён. Проверьте поле перед следующим вводом.',
      no_editor:'Выберите поле ввода на Android.', stale_editor:'Поле ввода изменилось. Повторите ввод в выбранном поле.',
      unavailable:'Клавиатура Android недоступна.', interrupted:'Ввод освобождён после действия другого клиента.' };
    const send = (command: RemoteKeyboardCommand) => {
      const c = current;
      if (!c) { setError(errors.not_sent); return; }
      void c.keyboard(command).then(receipt => {
        if (disposed || c !== current) return;
        setError(receipt.outcome === 'accepted' ? null : errors[receipt.outcome]);
      });
    };
    const generation = () => current?.keyboardState.editorGeneration ?? 0;
    const release = () => {
      if (held.size || composing) send({ operation:'reset', editor_generation:generation() });
      held.clear(); composing = false; lastCompositionInsert = null; input.value = '';
    };
    cleanupRef.current = release;
    const focus = () => {
      if (wantedRef.current && callbacks.current.available && current?.keyboardState.enabled) input.focus({ preventScroll:true });
    };
    const pointer = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && !target.closest('button,input,textarea,select,a,summary')) focus();
    };
    const tick = () => {
      const next = callbacks.current.available ? callbacks.current.controller() : null;
      if (next !== current) {
        release(); current = next; setReady(false);
        if (wantedRef.current && current?.state === 'ready' && current.supportsKeyboard) current.keyboardMode(true);
      }
      const enabled = !!current?.keyboardState.enabled && current.state === 'ready';
      setReady(enabled);
      if (wantedRef.current && current?.keyboardState.reason === 'unavailable') setError(errors.unavailable);
    };
    const meta = (event: KeyboardEvent) => (event.shiftKey ? 1:0) | (event.altKey ? 2:0) | (event.ctrlKey ? 4096:0)
      | (event.metaKey ? 65536:0) | (event.getModifierState('CapsLock') ? 1048576:0)
      | (event.getModifierState('NumLock') ? 2097152:0) | (event.getModifierState('ScrollLock') ? 4194304:0);
    const down = (event: KeyboardEvent) => {
      if (!wantedRef.current || !current?.keyboardState.enabled || event.isComposing || composing || event.key === 'Process') return;
      // Browser clipboard text comes from paste; do not also inject Android Ctrl+V.
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'v') return;
      const editor = current.keyboardState.editorActive;
      if (editor && ((!event.ctrlKey && !event.metaKey && !event.altKey) || event.getModifierState('AltGraph'))
        && (event.key.length === 1 || event.key === 'Dead')) return;
      if (!editor && /[^\x00-\x7f]/.test(event.key) && !event.ctrlKey && !event.metaKey) return;
      if (editor && ['Backspace','Delete'].includes(event.key)) {
        event.preventDefault(); send({ operation:event.key === 'Backspace' ? 'delete_backward':'delete_forward', editor_generation:generation() }); return;
      }
      const key = androidPhysicalKey(event.code);
      if (key === null) return;
      event.preventDefault();
      if (held.has(event.code)) return;
      held.set(event.code,key);
      send({ operation:'key_down', keycode:key, meta:meta(event), editor_generation:generation() });
    };
    const up = (event: KeyboardEvent) => {
      const key = held.get(event.code); if (key === undefined) return;
      event.preventDefault(); held.delete(event.code);
      send({ operation:'key_up', keycode:key, meta:meta(event), editor_generation:generation() });
    };
    const before = (event: InputEvent) => {
      if (!wantedRef.current || !current?.keyboardState.enabled) { event.preventDefault(); setError(errors.not_sent); return; }
      if (composing || event.isComposing || event.inputType === 'insertCompositionText' || event.inputType === 'insertFromComposition') return;
      event.preventDefault();
      if (event.inputType === 'insertFromPaste') return; // paste below is the sole clipboard submission.
      if (event.inputType === 'deleteContentBackward' || event.inputType === 'deleteContentForward') {
        send({ operation:event.inputType === 'deleteContentBackward' ? 'delete_backward':'delete_forward', editor_generation:generation() }); return;
      }
      if (event.data) {
        if (lastCompositionInsert === event.data) { lastCompositionInsert = null; return; }
        lastCompositionInsert = null;
        if (!validRemoteText(event.data)) { setError('Текст слишком длинный или содержит недопустимые символы.'); return; }
        send({ operation:'commit', text:event.data, editor_generation:generation() });
      }
    };
    const paste = (event: ClipboardEvent) => {
      event.preventDefault();
      const text = event.clipboardData?.getData('text/plain').replace(/\r\n?/g,'\n') ?? '';
      if (!text) return;
      if (!validRemoteText(text)) { setError('За один раз можно вставить до 1024 символов.'); return; }
      send({ operation:'commit', text, editor_generation:generation() });
    };
    const compositionStart = () => { composing = true; lastCompositionInsert = null; };
    const compositionUpdate = (event: CompositionEvent) => {
      if (validRemoteText(event.data)) send({ operation:'compose',text:event.data,editor_generation:generation() });
    };
    const compositionEnd = (event: CompositionEvent) => {
      composing = false; lastCompositionInsert = event.data; input.value = '';
      if (!validRemoteText(event.data)) { setError('Составной текст слишком длинный.'); release(); return; }
      send({ operation:'compose',text:event.data,editor_generation:generation() });
      send({ operation:'finish',editor_generation:generation() });
    };
    const hidden = () => { if (document.hidden) release(); };
    input.addEventListener('keydown',down); input.addEventListener('keyup',up); input.addEventListener('beforeinput',before);
    input.addEventListener('paste',paste); input.addEventListener('compositionstart',compositionStart);
    input.addEventListener('compositionupdate',compositionUpdate); input.addEventListener('compositionend',compositionEnd);
    input.addEventListener('blur',release); document.addEventListener('visibilitychange',hidden); window.addEventListener('blur',release);
    const surface = viewport.current; surface?.addEventListener('pointerdown',pointer);
    const timer = setInterval(tick,100); tick();
    return () => {
      disposed = true;
      release(); void current?.disableKeyboard(); clearInterval(timer); cleanupRef.current = () => {};
      input.removeEventListener('keydown',down); input.removeEventListener('keyup',up); input.removeEventListener('beforeinput',before);
      input.removeEventListener('paste',paste); input.removeEventListener('compositionstart',compositionStart);
      input.removeEventListener('compositionupdate',compositionUpdate); input.removeEventListener('compositionend',compositionEnd);
      input.removeEventListener('blur',release); document.removeEventListener('visibilitychange',hidden); window.removeEventListener('blur',release);
      surface?.removeEventListener('pointerdown',pointer);
    };
  }, [viewport]);
  const toggle = () => {
    const next = !wantedRef.current; wantedRef.current = next; setWanted(next); setError(null);
    if (!next) cleanupRef.current();
    const c = controller();
    if (next) {
      if (!c?.keyboardMode(true)) setError('Клавиатура доступна после подключения прямого управления и обновления APK.');
    } else void c?.disableKeyboard();
    if (next) textarea.current?.focus({ preventScroll:true });
  };
  return <div className="min-w-0 space-y-1">
    <button type="button" aria-pressed={wanted} disabled={!available} onClick={toggle}
      className="flex min-h-11 items-center gap-2 rounded-lg border border-border bg-background/90 px-3 py-2 text-xs hover:bg-muted disabled:opacity-50">
      <Keyboard className="h-4 w-4" aria-hidden />{wanted ? ready ? 'Клавиатура включена' : 'Подключаем клавиатуру…' : 'Ввод с клавиатуры'}
    </button>
    <textarea ref={textarea} aria-label="Ввод на Android" autoComplete="off" autoCorrect="off" spellCheck={false}
      tabIndex={wanted ? 0:-1} onInput={event => { if (!(event.nativeEvent as InputEvent).isComposing) event.currentTarget.value = ''; }}
      className="absolute h-px w-px resize-none overflow-hidden opacity-0" />
    {error && <p role="alert" className="max-w-md text-xs text-amber-600 dark:text-amber-300">{error}</p>}
  </div>;
}
