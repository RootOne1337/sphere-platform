import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';

function Editor({ layout = 'workspace' }: { layout?: 'workspace' | 'default' }) {
  const [draft, setDraft] = useState('');
  return <Dialog open><DialogContent layout={layout} aria-describedby={undefined}>
    <DialogHeader><DialogTitle>Рабочая форма</DialogTitle></DialogHeader>
    <DialogBody><input aria-label="Черновик" value={draft} onChange={e => setDraft(e.target.value)} /></DialogBody>
    <DialogFooter><button>Проверить</button></DialogFooter>
  </DialogContent></Dialog>;
}

let original: PropertyDescriptor | undefined;
let viewport: EventTarget & { height: number; offsetTop: number };
beforeEach(() => {
  original = Object.getOwnPropertyDescriptor(window, 'visualViewport');
  viewport = Object.assign(new EventTarget(), { height: 800, offsetTop: 0 });
  Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });
});
afterEach(() => {
  if (original) Object.defineProperty(window, 'visualViewport', original);
  else Reflect.deleteProperty(window, 'visualViewport');
});

it('follows a resized and panned visual viewport without replacing a focused draft', async () => {
  render(<Editor />);
  const dialog = screen.getByRole('dialog');
  const draft = screen.getByLabelText('Черновик');
  draft.focus(); fireEvent.change(draft, { target: { value: 'Несохранённое значение' } });
  await waitFor(() => expect(dialog.style.getPropertyValue('--dialog-viewport-height')).toBe('800px'));
  act(() => { viewport.height = 380; viewport.offsetTop = 24; viewport.dispatchEvent(new Event('resize')); viewport.dispatchEvent(new Event('scroll')); });
  await waitFor(() => expect(dialog.style.getPropertyValue('--dialog-viewport-height')).toBe('380px'));
  expect(dialog.style.getPropertyValue('--dialog-viewport-top')).toBe('24px');
  expect(screen.getByLabelText('Черновик')).toBe(draft);
  expect(draft).toHaveValue('Несохранённое значение'); expect(draft).toHaveFocus();
  const body = dialog.querySelector('[data-dialog-body]')!;
  expect(body).toContainElement(draft);
  expect(body).not.toContainElement(screen.getByRole('button', { name: 'Проверить' }));
});

it('ignores transient invalid geometry and detaches viewport listeners when closed', async () => {
  const remove = jest.spyOn(viewport, 'removeEventListener');
  const view = render(<Editor />);
  const dialog = screen.getByRole('dialog');
  await waitFor(() => expect(dialog.style.getPropertyValue('--dialog-viewport-height')).toBe('800px'));
  act(() => { viewport.height = 0; viewport.dispatchEvent(new Event('resize')); });
  await act(async () => { await new Promise(resolve => requestAnimationFrame(resolve)); });
  expect(dialog.style.getPropertyValue('--dialog-viewport-height')).toBe('800px');
  view.unmount();
  expect(remove).toHaveBeenCalledWith('resize', expect.any(Function));
  expect(remove).toHaveBeenCalledWith('scroll', expect.any(Function));
});

it('leaves conventional dialogs independent of visual viewport events', () => {
  const add = jest.spyOn(viewport, 'addEventListener');
  render(<Editor layout="default" />);
  expect(add).not.toHaveBeenCalled();
  expect(screen.getByRole('dialog').style.getPropertyValue('--dialog-viewport-height')).toBe('');
});
