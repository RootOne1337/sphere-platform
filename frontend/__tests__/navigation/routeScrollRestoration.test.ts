import { createRouteScrollRestoration, hasPreviousRoute, returnToPreviousRoute } from '@/src/features/navigation/routeScrollRestoration';

const originalPush = window.history.pushState;
const originalReplace = window.history.replaceState;
let main: HTMLDivElement;
let controller: ReturnType<typeof createRouteScrollRestoration>;
let resized: ResizeObserverCallback;
let frame: (() => void) | undefined;

beforeEach(() => {
  originalReplace.call(window.history, { __NA: true, tree: ['framework-owned'] }, '', '/scripts');
  main = document.createElement('div'); main.append(document.createElement('div')); document.body.append(main);
  jest.spyOn(window, 'requestAnimationFrame').mockImplementation(callback => { frame = () => callback(0); return 1; });
  jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined);
  Object.defineProperty(window, 'ResizeObserver', { configurable: true, value: class {
    constructor(callback: ResizeObserverCallback) { resized = callback; }
    observe() {} disconnect() {}
  } });
  controller = createRouteScrollRestoration(main); controller.routeRendered('/scripts');
});
afterEach(() => { controller.dispose(); main.remove(); jest.restoreAllMocks(); });

function remember(top: number) { main.scrollTop = top; main.dispatchEvent(new Event('scroll')); frame?.(); }
function pop(state: unknown, url: string) {
  originalReplace.call(window.history, state, '', url);
  window.dispatchEvent(new PopStateEvent('popstate', { state }));
  controller.routeRendered(url);
}

it('restores Back and Forward entries while preserving framework state and resetting new routes', () => {
  const catalogState = window.history.state;
  remember(742);
  window.history.pushState({ __NA: true, tree: ['new-framework-tree'] }, '', '/scripts/builder?id=a');
  const builderState = window.history.state;
  controller.routeRendered('/scripts/builder?id=a');
  expect(main.scrollTop).toBe(0);
  expect(window.history.state).toMatchObject({ __NA: true, tree: ['new-framework-tree'] });
  remember(215);
  pop(catalogState, '/scripts'); expect(main.scrollTop).toBe(742);
  pop(builderState, '/scripts/builder?id=a'); expect(main.scrollTop).toBe(215);
});

it('does not collapse two visits to the same URL into one saved position', () => {
  const first = window.history.state; remember(650);
  window.history.pushState({}, '', '/devices'); controller.routeRendered('/devices');
  remember(80);
  window.history.pushState({}, '', '/scripts'); controller.routeRendered('/scripts');
  const second = window.history.state; remember(145);
  pop(first, '/scripts'); expect(main.scrollTop).toBe(650);
  pop(second, '/scripts'); expect(main.scrollTop).toBe(145);
});

it('retains departure geometry when a framework render clamps the main before history is written', () => {
  const state = window.history.state; remember(1440);
  const link = document.createElement('a'); link.href = '/scripts/builder?id=a'; main.append(link);
  link.addEventListener('click', event => event.preventDefault());
  link.click();
  main.scrollTop = 0; main.dispatchEvent(new Event('scroll')); frame?.();
  window.history.pushState({}, '', '/scripts/builder?id=a'); controller.routeRendered('/scripts/builder?id=a');
  pop(state, '/scripts'); expect(main.scrollTop).toBe(1440);
});

it('normalizes query encoding without sharing positions between different filter queries', () => {
  window.history.pushState({}, '', '/scripts?search=two%20words');
  controller.routeRendered('/scripts?search=two+words'); remember(315);
  const filtered = window.history.state;
  window.history.pushState({}, '', '/scripts?search=other'); controller.routeRendered('/scripts?search=other');
  expect(main.scrollTop).toBe(0);
  originalReplace.call(window.history, filtered, '', '/scripts?search=two%20words');
  window.dispatchEvent(new PopStateEvent('popstate', { state: filtered }));
  controller.routeRendered('/scripts?search=two+words'); expect(main.scrollTop).toBe(315);
});

it('restores named inner scroll areas without storing DOM nodes or business data in history', () => {
  const pane = document.createElement('div'); pane.dataset.routeScroll = 'studio-device'; main.append(pane);
  const state = window.history.state; main.scrollTop = 10; pane.scrollTop = 312;
  pane.dispatchEvent(new Event('scroll')); frame?.();
  window.history.pushState({}, '', '/devices'); controller.routeRendered('/devices');
  main.scrollTop = 0; pane.scrollTop = 0;
  pop(state, '/scripts');
  expect(main.scrollTop).toBe(10); expect(pane.scrollTop).toBe(312);
  expect(Object.keys(window.history.state).sort()).toEqual(['__NA', '__sphereScrollEntry', 'tree']);
});

it('waits boundedly for asynchronously loaded content to grow instead of accepting its initial clamp', () => {
  const state = window.history.state; remember(800);
  window.history.pushState({}, '', '/devices'); controller.routeRendered('/devices');
  let position = 0, maximum = 200;
  Object.defineProperty(main, 'scrollTop', { configurable: true, get: () => position,
    set: value => { position = Math.min(maximum, value); } });
  pop(state, '/scripts'); expect(position).toBe(200);
  maximum = 1000; resized([], {} as ResizeObserver); expect(position).toBe(800);
});

it('lets the operator scroll during deferred restoration and never jumps back over that action', () => {
  const state = window.history.state; remember(800);
  window.history.pushState({}, '', '/devices'); controller.routeRendered('/devices');
  let position = 0, maximum = 200;
  Object.defineProperty(main, 'scrollTop', { configurable: true, get: () => position,
    set: value => { position = Math.min(maximum, value); } });
  pop(state, '/scripts');
  main.dispatchEvent(new WheelEvent('wheel')); position = 123;
  maximum = 1000; resized([], {} as ResizeObserver); expect(position).toBe(123);
});

it('returns to an observed internal predecessor and uses the safe parent fallback for a direct entry', () => {
  const push = jest.fn(); const back = jest.spyOn(window.history, 'back').mockImplementation(() => undefined);
  expect(hasPreviousRoute()).toBe(false);
  returnToPreviousRoute('/dashboard', push); expect(push).toHaveBeenCalledWith('/dashboard');
  window.history.pushState({}, '', '/scripts/builder?id=a'); controller.routeRendered('/scripts/builder?id=a');
  expect(hasPreviousRoute()).toBe(true);
  returnToPreviousRoute('/scripts', push, '/scripts'); expect(back).toHaveBeenCalledTimes(1);
  returnToPreviousRoute('/devices', push, '/devices'); expect(push).toHaveBeenLastCalledWith('/devices');
});

it('bounds retained entries and restores history methods without overriding another owner', () => {
  for (let index = 0; index < 150; index++) {
    remember(index); window.history.pushState({}, '', `/devices?page=${index}`); controller.routeRendered(`/devices?page=${index}`);
  }
  expect(controller.retainedEntries()).toBe(80);
  const anotherOwner = jest.fn(); window.history.pushState = anotherOwner;
  controller.dispose(); expect(window.history.pushState).toBe(anotherOwner);
  expect(window.history.replaceState).toBe(originalReplace);
  expect(hasPreviousRoute()).toBe(false); window.history.pushState = originalPush;
});

it('clears old coordinates on controller replacement rather than carrying them into another identity', () => {
  const state = window.history.state; remember(800); controller.dispose();
  controller = createRouteScrollRestoration(main); controller.routeRendered('/scripts');
  expect(main.scrollTop).toBe(0);
  window.dispatchEvent(new PopStateEvent('popstate', { state })); controller.routeRendered('/scripts');
  expect(main.scrollTop).toBe(0);
});
