import { fireEvent, render, screen } from '@testing-library/react';
import { MobileMenuHandle } from '@/src/features/navigation/MobileMenuHandle';

function pointer(element: Element, name: string, x: number, y: number) {
  const event=new MouseEvent(name,{bubbles:true,clientX:x,clientY:y});
  Object.defineProperties(event,{pointerType:{value:'touch'},isPrimary:{value:true},pointerId:{value:1}});
  fireEvent(element,event);
}
it('opens from its dedicated horizontal handle and retains a click alternative',()=>{
  const open=jest.fn();render(<MobileMenuHandle onOpen={open}/>);
  const handle=screen.getByRole('button',{name:'Открыть меню: потяните вправо'});
  pointer(handle,'pointerdown',4,200);pointer(handle,'pointermove',72,206);pointer(handle,'pointerup',72,206);
  expect(open).toHaveBeenCalledTimes(1);fireEvent.click(handle);expect(open).toHaveBeenCalledTimes(2);
});
it('ignores vertical page scroll, short moves and cancelled gestures',()=>{
  const open=jest.fn();render(<MobileMenuHandle onOpen={open}/>);const handle=screen.getByRole('button');
  pointer(handle,'pointerdown',4,200);pointer(handle,'pointermove',8,250);pointer(handle,'pointermove',90,250);
  pointer(handle,'pointerdown',4,200);pointer(handle,'pointermove',30,200);pointer(handle,'pointerup',30,200);
  pointer(handle,'pointerdown',4,200);pointer(handle,'pointercancel',4,200);pointer(handle,'pointermove',90,200);
  expect(open).not.toHaveBeenCalled();
});
