'use client';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Keyboard } from 'lucide-react';
import type { ContinuousPointer } from './continuousPointer';
import { androidPhysicalKey, validRemoteText, type RemoteKeyboardCommand } from './remoteKeyboardProtocol';

/** Focused remote input only. No global typing/clipboard listeners and no reconnect replay. */
export function RemoteKeyboardCapture({ controller, available, viewport }: {
  controller: () => ContinuousPointer | null; available: boolean; viewport: React.RefObject<HTMLElement | null>;
}) {
  const callbacks = useRef({ controller, available }); callbacks.current = { controller, available };
  const textarea = useRef<HTMLTextAreaElement>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  useEffect(() => { setHost(viewport.current); }, [viewport]);
  const [wanted, setWanted] = useState(true), [ready, setReady] = useState(false), [editorActive, setEditorActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wantedRef = useRef(true);
  const cleanupRef = useRef<() => void>(() => {});
  useEffect(() => {
    const input = textarea.current;
    if (!input) return;
    let current: ContinuousPointer | null = null, requested: ContinuousPointer | null = null, composing = false, lastCompositionInsert: string | null = null, disposed = false;
    let touch = false, recentTouch = 0, wasEditor = false;
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
    const focus = (soft = false) => {
      if (!wantedRef.current || !callbacks.current.available || !current?.keyboardState.enabled) return;
      // A touch on the game/video is not a request for the phone's soft keyboard.
      input.inputMode = soft && current.keyboardState.editorActive ? 'text' : 'none';
      input.focus({ preventScroll:true });
    };
    const pointer = (event: PointerEvent) => {
      const target = event.target;
      // The inspector itself is a dialog. Only controls within this stream,
      // rather than its containing dialog, should prevent remote keyboard focus.
      if (target instanceof Element && viewport.current?.contains(target)
        && !target.closest('button,input,textarea,select,a,summary') && target.closest('canvas')) {
        touch = event.pointerType === 'touch' || event.pointerType === 'pen';
        if (touch) recentTouch = Date.now();
        focus(touch);
      }
    };
    const tick = () => {
      const next = callbacks.current.available ? callbacks.current.controller() : null;
      if (next !== current) {
        release(); current = next; requested = null; setReady(false);
      }
      if (wantedRef.current && current?.state === 'ready' && current.supportsKeyboard && requested !== current) {
        if (current.keyboardMode(true)) requested = current;
      }
      const enabled = !!current?.keyboardState.enabled && current.state === 'ready';
      setReady(enabled);
      const editor = enabled && !!current?.keyboardState.editorActive;
      setEditorActive(editor);
      if (!editor && touch) input.inputMode = 'none';
      // Android reports the focused editor after the click ACK. Chrome can then
      // show its IME; browsers requiring a fresh user activation use the explicit icon.
      if (editor && !wasEditor && touch && Date.now() - recentTouch < 1500 && document.activeElement === input) {
        input.blur(); focus(true);
      }
      wasEditor = editor;
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
    const surface = viewport.current; surface?.addEventListener('pointerup',pointer);
    const timer = setInterval(tick,100); tick();
    return () => {
      disposed = true;
      release(); void current?.disableKeyboard(); clearInterval(timer); cleanupRef.current = () => {};
      input.removeEventListener('keydown',down); input.removeEventListener('keyup',up); input.removeEventListener('beforeinput',before);
      input.removeEventListener('paste',paste); input.removeEventListener('compositionstart',compositionStart);
      input.removeEventListener('compositionupdate',compositionUpdate); input.removeEventListener('compositionend',compositionEnd);
      input.removeEventListener('blur',release); document.removeEventListener('visibilitychange',hidden); window.removeEventListener('blur',release);
      surface?.removeEventListener('pointerup',pointer);
    };
  }, [viewport, host]);
  const toggle = () => {
    const next = !wantedRef.current; wantedRef.current = next; setWanted(next); setError(null);
    if (!next) cleanupRef.current();
    const c = controller();
    if (next) {
      if (!c?.keyboardMode(true)) setError('Клавиатура доступна после подключения прямого управления и обновления APK.');
    } else void c?.disableKeyboard();
    if (next && textarea.current) { textarea.current.inputMode = 'none'; textarea.current.focus({ preventScroll:true }); }
  };
  return <div className="min-w-0 space-y-1">
    <div className="flex flex-wrap gap-1"><button type="button" aria-label={wanted ? 'Отключить аппаратную клавиатуру' : 'Включить аппаратную клавиатуру'} aria-pressed={wanted} disabled={!available} onClick={toggle}
      className="flex min-h-11 items-center gap-2 rounded-lg border border-border bg-background/90 px-3 py-2 text-xs hover:bg-muted disabled:opacity-50">
      <Keyboard className="h-4 w-4" aria-hidden /><span>{wanted ? ready ? 'Клавиатура' : 'Подключаем клавиатуру…' : 'Клавиатура выключена'}</span>
    </button>
    {wanted && ready && editorActive && <button type="button" aria-label="Открыть экранную клавиатуру" title="Поле Android готово к вводу"
      className="flex min-h-11 items-center gap-2 rounded-lg border border-border bg-background/90 px-3 py-2 text-xs hover:bg-muted"
      onClick={() => { const input = textarea.current; if (input) { input.inputMode = 'text'; input.focus({ preventScroll:true }); } }}><Keyboard className="h-4 w-4" aria-hidden />Печатать</button>}
    </div>
    {host && createPortal(<textarea ref={textarea} aria-label="Ввод на Android" inputMode="none" autoComplete="off" autoCorrect="off" spellCheck={false}
      tabIndex={-1} onInput={event => { if (!(event.nativeEvent as InputEvent).isComposing) event.currentTarget.value = ''; }}
      className="absolute left-0 top-0 h-px w-px resize-none overflow-hidden opacity-0" />, host)}
    {error && <p role="alert" className="max-w-md text-xs text-amber-600 dark:text-amber-300">{error}</p>}
  </div>;
}
