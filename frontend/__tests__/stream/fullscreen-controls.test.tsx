import { act, fireEvent, render, screen } from '@testing-library/react';
import { useRef } from 'react';
import { useStreamFullscreen } from '@/src/features/stream/useStreamFullscreen';
import { StreamControlsTray } from '@/src/features/stream/StreamControlsTray';

let owner: Element | null, request: jest.Mock, exit: jest.Mock;
function Harness() {
  const full = useStreamFullscreen();
  return <div ref={full.ref} data-testid="viewport" data-active={full.active}>
    <video data-testid="retained-video" />
    <button disabled={!full.available} onClick={() => void full.toggle()}>Fullscreen</button>
    {full.error && <p role="status">{full.error}</p>}
  </div>;
}
beforeEach(() => {
  owner = null;
  Object.defineProperty(document, 'fullscreenEnabled', { configurable: true, value: true });
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => owner });
  request = jest.fn(function (this: Element) {
    owner = this; document.dispatchEvent(new Event('fullscreenchange')); return Promise.resolve();
  });
  exit = jest.fn(async () => { owner = null; document.dispatchEvent(new Event('fullscreenchange')); });
  Object.defineProperty(HTMLElement.prototype, 'requestFullscreen', { configurable: true, value: request });
  Object.defineProperty(document, 'exitFullscreen', { configurable: true, value: exit });
});

test('native enter and browser exit keep the exact video element mounted', async () => {
  render(<Harness />);
  const video = screen.getByTestId('retained-video'), viewport = screen.getByTestId('viewport');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Fullscreen' })));
  expect(viewport).toHaveAttribute('data-active', 'true');
  expect(request).toHaveBeenCalledTimes(1);
  expect(screen.getByTestId('retained-video')).toBe(video);
  act(() => { owner = null; document.dispatchEvent(new Event('fullscreenchange')); });
  expect(viewport).toHaveAttribute('data-active', 'false');
  expect(screen.getByTestId('retained-video')).toBe(video);
});

test('another fullscreen owner is never exited or replaced', async () => {
  owner = document.createElement('div');
  const view = render(<Harness />);
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Fullscreen' })));
  expect(request).not.toHaveBeenCalled(); expect(exit).not.toHaveBeenCalled();
  expect(screen.getByRole('status')).toHaveTextContent('Видеопоток продолжает работать');
  view.unmount(); expect(exit).not.toHaveBeenCalled();
});

test('unsupported or rejected fullscreen never removes the stream', async () => {
  Object.defineProperty(document, 'fullscreenEnabled', { configurable: true, value: false });
  const view = render(<Harness />);
  expect(screen.getByRole('button', { name: 'Fullscreen' })).toBeDisabled();
  view.unmount();
  Object.defineProperty(document, 'fullscreenEnabled', { configurable: true, value: true });
  request.mockRejectedValue(new Error('denied'));
  render(<Harness />); const video = screen.getByTestId('retained-video');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Fullscreen' })));
  expect(screen.getByRole('status')).toHaveTextContent('Браузер не разрешил');
  expect(screen.getByTestId('retained-video')).toBe(video);
});

test('rapid clicks share one outstanding native request and owned teardown exits', async () => {
  let finish!: () => void;
  request.mockImplementation(function (this: Element) {
    const element = this;
    return new Promise<void>(resolve => { finish = () => { owner = element; resolve(); }; });
  });
  const view = render(<Harness />);
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen' }));
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen' }));
  expect(request).toHaveBeenCalledTimes(1);
  view.unmount();
  await act(async () => finish());
  expect(exit).toHaveBeenCalledTimes(1); expect(owner).toBeNull();
});

function Tray({ overlay = true }: { overlay?: boolean }) {
  const viewport = useRef<HTMLDivElement>(null);
  return <><div ref={viewport} data-testid="surface">
    <StreamControlsTray viewport={viewport} overlay={overlay}><button>Домой</button></StreamControlsTray>
  </div><button>Другой элемент</button></>;
}
function move(y: number, pointerType = 'mouse') {
  const surface = screen.getByTestId('surface');
  jest.spyOn(surface, 'getBoundingClientRect').mockReturnValue({ top: 0, bottom: 400, left: 0, right: 400, width: 400, height: 400, x: 0, y: 0, toJSON: () => ({}) });
  const event = new MouseEvent('pointermove', { clientX: 200, clientY: y, bubbles: true, cancelable: true });
  Object.defineProperty(event, 'pointerType', { value: pointerType });
  act(() => surface.dispatchEvent(event));
  return event;
}

test('touch can reveal and hide Android controls without a hover or synthetic gesture', () => {
  render(<Tray />);
  expect(screen.queryByRole('button', { name: 'Домой' })).not.toBeInTheDocument();
  expect(move(395, 'touch').defaultPrevented).toBe(false);
  expect(screen.queryByRole('button', { name: 'Домой' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Показать панель Android' }));
  expect(screen.getByRole('button', { name: 'Домой' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Скрыть панель Android' }));
  expect(screen.queryByRole('button', { name: 'Домой' })).not.toBeInTheDocument();
});

test('mouse edge detection does not consume input and focused controls stay reachable', () => {
  render(<Tray />);
  expect(move(390).defaultPrevented).toBe(false);
  const home = screen.getByRole('button', { name: 'Домой' });
  fireEvent.focus(home); move(200);
  expect(screen.getByRole('button', { name: 'Домой' })).toBe(home);
  fireEvent.blur(home, { relatedTarget: screen.getByRole('button', { name: 'Другой элемент' }) });
  expect(screen.queryByRole('button', { name: 'Домой' })).not.toBeInTheDocument();
});

test('changing presentation keeps the same controls and regular mode stays visible', () => {
  const view = render(<Tray overlay={false} />), home = screen.getByRole('button', { name: 'Домой' });
  expect(screen.queryByRole('button', { name: 'Показать панель Android' })).not.toBeInTheDocument();
  view.rerender(<Tray />);
  fireEvent.click(screen.getByRole('button', { name: 'Показать панель Android' }));
  expect(screen.getByRole('button', { name: 'Домой' })).toBe(home);
});
