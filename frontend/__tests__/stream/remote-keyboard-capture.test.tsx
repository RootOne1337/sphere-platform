import { act,fireEvent,render } from '@testing-library/react';
import { createRef } from 'react';
import { RemoteKeyboardCapture } from '@/src/features/stream/RemoteKeyboardCapture';
import type { ContinuousPointer } from '@/src/features/stream/continuousPointer';

function fixture(editor=true) {
  const viewport=document.createElement('div');document.body.append(viewport);
  const ref=createRef<HTMLElement>();ref.current=viewport;
  const state={enabled:false,editorGeneration:7,editorActive:editor,reason:'disabled'};
  const keyboard=jest.fn().mockResolvedValue({outcome:'accepted',receiptRoundTripMs:1});
  const mode=jest.fn(enabled=>{state.enabled=enabled;return true});
  const disable=jest.fn(async()=>{state.enabled=false;});
  const controller={state:'ready',supportsKeyboard:true,keyboardState:state,keyboard,keyboardMode:mode,disableKeyboard:disable} as unknown as ContinuousPointer;
  const view=render(<RemoteKeyboardCapture controller={()=>controller} available viewport={ref}/>);

  const input=view.getByLabelText('Ввод на Android');
  const before=(data:string)=>input.dispatchEvent(new InputEvent('beforeinput',{bubbles:true,cancelable:true,inputType:'insertText',data}));
  const cleanup=()=>{view.unmount();viewport.remove();act(()=>jest.runOnlyPendingTimers());};
  return {view,input,before,state,keyboard,mode,disable,cleanup,viewport};
}
beforeEach(()=>jest.useFakeTimers());afterEach(()=>jest.useRealTimers());
test('focused editor Unicode is submitted exactly once and never also sent as a physical key',async()=>{
  const f=fixture();fireEvent.keyDown(f.input,{code:'KeyA',key:'a'});
  act(()=>{f.before('Привет 🙂');});await act(async()=>{});
  expect(f.keyboard.mock.calls.map(c=>c[0])).toEqual([{operation:'commit',editor_generation:7,text:'Привет 🙂'}]);
  f.cleanup();expect(jest.getTimerCount()).toBe(0);
});
test('game input has explicit held DOWN UP and releases a held key on blur',async()=>{
  const f=fixture(false);
  fireEvent.keyDown(f.input,{code:'KeyW',key:'w'});fireEvent.keyDown(f.input,{code:'KeyW',key:'w',repeat:true});
  fireEvent.keyUp(f.input,{code:'KeyW',key:'w'});fireEvent.keyDown(f.input,{code:'ShiftLeft',key:'Shift',shiftKey:true});
  fireEvent.blur(f.input);await act(async()=>{});
  expect(f.keyboard.mock.calls.map(c=>c[0].operation)).toEqual(['key_down','key_up','key_down','reset']);
  expect(f.keyboard.mock.calls[0][0].keycode).toBe(51);
  f.cleanup();expect(jest.getTimerCount()).toBe(0);
});
test('composition and clipboard have one input source and no printable duplicate',async()=>{
  const f=fixture();fireEvent.compositionStart(f.input);fireEvent.compositionUpdate(f.input,{data:'に'});
  act(()=>f.input.dispatchEvent(new InputEvent('beforeinput',{bubbles:true,inputType:'insertCompositionText',data:'に',isComposing:true})));
  fireEvent.compositionEnd(f.input,{data:'日本'});act(()=>f.before('日本'));
  fireEvent.paste(f.input,{clipboardData:{getData:()=> 'line1\r\nПривет'}});await act(async()=>{});
  expect(f.keyboard.mock.calls.map(c=>c[0])).toEqual([
    {operation:'compose',editor_generation:7,text:'に'}, {operation:'compose',editor_generation:7,text:'日本'},
    {operation:'finish',editor_generation:7}, {operation:'commit',editor_generation:7,text:'line1\nПривет'}]);
  f.cleanup();expect(jest.getTimerCount()).toBe(0);
});
test('typing elsewhere in the browser is not captured and unready typing is explicit',async()=>{
  const f=fixture();fireEvent.keyDown(document.body,{code:'KeyW',key:'w'});expect(f.keyboard).not.toHaveBeenCalled();
  f.state.enabled=false;act(()=>f.before('lost?'));await act(async()=>{});
  expect(f.keyboard).not.toHaveBeenCalled();expect(f.view.getByRole('alert')).toHaveTextContent('не отправлен');
  f.cleanup();expect(jest.getTimerCount()).toBe(0);
});

test('hardware mode is automatic; a touch on a game never requests a soft keyboard',()=>{
  const f=fixture(false);const canvas=document.createElement('canvas');f.viewport.append(canvas);
  const pointer=new MouseEvent('pointerup',{bubbles:true});Object.defineProperty(pointer,'pointerType',{value:'touch'});
  act(()=>canvas.dispatchEvent(pointer));
  expect(f.mode).toHaveBeenCalledWith(true);expect(f.input).toHaveAttribute('inputmode','none');expect(f.input).toHaveFocus();
  expect(f.view.queryByRole('button',{name:'Открыть экранную клавиатуру'})).not.toBeInTheDocument();
  f.cleanup();
});

test('stream canvas in the device inspector dialog still focuses its own hardware input',()=>{
  const f=fixture(false);const dialog=document.createElement('div');dialog.setAttribute('role','dialog');document.body.append(dialog);dialog.append(f.viewport);
  const canvas=document.createElement('canvas');f.viewport.append(canvas);
  act(()=>fireEvent.pointerUp(canvas,{pointerType:'mouse'}));
  expect(f.input).toHaveFocus();expect(f.input).toHaveAttribute('inputmode','none');
  f.cleanup();dialog.remove();
});

test('a different stream canvas does not steal keyboard focus',()=>{
  const f=fixture(false);const outside=document.createElement('button');document.body.append(outside);outside.focus();
  const other=document.createElement('canvas');document.body.append(other);
  act(()=>fireEvent.pointerUp(other,{pointerType:'mouse'}));
  expect(outside).toHaveFocus();
  f.cleanup();outside.remove();other.remove();
});

test('soft keyboard action is offered only for an Android editor and remains outside hidden trays',()=>{
  const f=fixture();act(()=>jest.advanceTimersByTime(100));
  fireEvent.click(f.view.getByRole('button',{name:'Открыть экранную клавиатуру'}));
  expect(f.input).toHaveAttribute('inputmode','text');expect(f.input.parentElement).toBe(f.viewport);
  f.state.editorActive=false;act(()=>jest.advanceTimersByTime(100));
  expect(f.view.queryByRole('button',{name:'Открыть экранную клавиатуру'})).not.toBeInTheDocument();
  f.cleanup();
});
