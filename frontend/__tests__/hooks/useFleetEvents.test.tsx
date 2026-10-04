import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactNode } from 'react';
import { useAuthStore } from '@/lib/store';
import { useFleetEvents } from '@/lib/hooks/useFleetEvents';

class TestWebSocket {
  static OPEN = 1;
  static instances: TestWebSocket[] = [];
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {
    TestWebSocket.instances.push(this);
  }

  send = jest.fn();
  close = jest.fn(() => { this.readyState = 3; });
  open() { this.readyState = 1; this.onopen?.(new Event('open')); }
  message(data: unknown) { this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent); }
  serverClose(code = 1006) { this.readyState = 3; this.onclose?.({ code } as CloseEvent); }
}

describe('useFleetEvents', () => {
  const originalWebSocket = global.WebSocket;

  beforeEach(() => {
    jest.useFakeTimers();
    TestWebSocket.instances = [];
    global.WebSocket = TestWebSocket as unknown as typeof WebSocket;
    Object.defineProperty(navigator, 'onLine', { value: true, configurable: true });
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
    act(() => useAuthStore.setState({ accessToken: 'test-token' }));
  });

  afterEach(() => {
    global.WebSocket = originalWebSocket;
    act(() => useAuthStore.setState({ accessToken: null }));
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  it('invalidates device queries for the backend device.status_change event', () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidate = jest.spyOn(client, 'invalidateQueries');
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    renderHook(() => useFleetEvents(), { wrapper });
    act(() => jest.runOnlyPendingTimers());
    const socket = TestWebSocket.instances[0];
    expect(socket).toBeDefined();

    act(() => {
      socket.onmessage?.({
        data: JSON.stringify({
          event_type: 'device.status_change',
          device_id: 'device-1',
          payload: { status: 'connecting' },
          ts: new Date().toISOString(),
        }),
      } as MessageEvent);
    });

    act(() => jest.advanceTimersByTime(500));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['devices'] }, { cancelRefetch: false });
  });

  function mount(onEvent?: (event: unknown) => void) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const invalidate = jest.spyOn(client, 'invalidateQueries');
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const view = renderHook(({ callback }) => useFleetEvents(callback), { wrapper, initialProps: { callback: onEvent } });
    act(() => jest.advanceTimersByTime(0));
    return { ...view, invalidate };
  }
  function authenticate(socket = TestWebSocket.instances.at(-1)!) {
    act(() => { socket.open(); socket.message({ type: 'pong' }); jest.advanceTimersByTime(500); });
    return socket;
  }

  it('does not call a TCP-open socket live until the server responds after authentication', () => {
    const view = mount();
    const socket = TestWebSocket.instances[0];
    act(() => socket.open());
    expect(view.result.current.state).toBe('connecting');
    expect(socket.send.mock.calls.map(call => JSON.parse(call[0]))).toEqual([{ token: 'test-token' }, { type: 'ping' }]);
    act(() => socket.message({ type: 'pong' }));
    expect(view.result.current.state).toBe('live');
  });
  it('reconciles REST state on initial snapshot and after a connection gap', () => {
    const view = mount();
    const first = authenticate();
    view.invalidate.mockClear();
    act(() => first.serverClose());
    expect(view.result.current.state).toBe('reconnecting');
    act(() => jest.advanceTimersByTime(1200));
    const next = TestWebSocket.instances[1];
    act(() => { next.open(); next.message({ type: 'snapshot', data: {} }); jest.advanceTimersByTime(500); });
    expect(view.result.current.state).toBe('live');
    for (const root of ['devices', 'dashboard', 'tasks', 'pipeline-runs', 'device-events']) {
      expect(view.invalidate).toHaveBeenCalledWith({ queryKey: [root] }, { cancelRefetch: false });
    }
  });
  it('coalesces a burst of progress events without repeatedly cancelling reads', () => {
    const view = mount();
    const socket = authenticate();
    view.invalidate.mockClear();
    act(() => {
      for (let i = 0; i < 100; i++) socket.message({ event_type: 'task.progress', payload: { progress: i } });
    });
    expect(view.invalidate).not.toHaveBeenCalled();
    act(() => jest.advanceTimersByTime(500));
    expect(view.invalidate.mock.calls.filter(call => call[0]?.queryKey?.[0] === 'tasks')).toHaveLength(1);
    expect(view.invalidate).toHaveBeenCalledWith({ queryKey: ['dashboard'] }, { cancelRefetch: false });
  });
  it('recovers a silently broken transport even when close/error never arrive', () => {
    const view = mount();
    const socket = authenticate();
    act(() => jest.advanceTimersByTime(19_500));
    expect(socket.send).toHaveBeenLastCalledWith(JSON.stringify({ type: 'ping' }));
    act(() => jest.advanceTimersByTime(10_000));
    expect(socket.close).toHaveBeenCalledTimes(1);
    expect(view.result.current.state).toBe('reconnecting');
    act(() => jest.advanceTimersByTime(1200));
    expect(TestWebSocket.instances).toHaveLength(2);
  });
  it('bounds a handshake that never opens or never answers', () => {
    const view = mount();
    act(() => jest.advanceTimersByTime(15_000));
    expect(TestWebSocket.instances[0].close).toHaveBeenCalled();
    expect(view.result.current.state).toBe('reconnecting');
  });
  it('does not loop on an authentication rejection until the token changes', () => {
    const view = mount();
    act(() => TestWebSocket.instances[0].serverClose(4001));
    expect(view.result.current.state).toBe('unauthorized');
    act(() => { window.dispatchEvent(new Event('online')); jest.advanceTimersByTime(120_000); });
    expect(TestWebSocket.instances).toHaveLength(1);
    act(() => useAuthStore.setState({ accessToken: 'replacement-token' }));
    act(() => jest.advanceTimersByTime(0));
    expect(TestWebSocket.instances).toHaveLength(2);
    act(() => TestWebSocket.instances[1].open());
    expect(TestWebSocket.instances[1].send).toHaveBeenCalledWith(JSON.stringify({ token: 'replacement-token' }));
  });
  it('recovers on browser network return and stops retrying while offline', () => {
    const view = mount();
    authenticate();
    act(() => {
      Object.defineProperty(navigator, 'onLine', { value: false, configurable: true });
      window.dispatchEvent(new Event('offline'));
      jest.advanceTimersByTime(60_000);
    });
    expect(view.result.current.state).toBe('offline');
    expect(TestWebSocket.instances).toHaveLength(1);
    act(() => {
      Object.defineProperty(navigator, 'onLine', { value: true, configurable: true });
      window.dispatchEvent(new Event('online'));
    });
    expect(TestWebSocket.instances).toHaveLength(2);
    authenticate();
    expect(view.result.current.state).toBe('live');
  });
  it('keeps the transport when a render supplies a new callback and isolates callback failures', () => {
    const view = mount();
    const socket = authenticate();
    const callback = jest.fn(() => { throw new Error('UI callback failed'); });
    view.rerender({ callback });
    expect(TestWebSocket.instances).toHaveLength(1);
    view.invalidate.mockClear();
    act(() => { socket.message({ event_type: 'command.completed' }); jest.advanceTimersByTime(500); });
    expect(callback).toHaveBeenCalledTimes(1);
    expect(view.invalidate).toHaveBeenCalledWith({ queryKey: ['device-inspector'] }, { cancelRefetch: false });
    expect(view.result.current.state).toBe('live');
  });
  it('defers background invalidations and reconciles them on returning to the tab', () => {
    const view = mount();
    const socket = authenticate();
    view.invalidate.mockClear();
    act(() => {
      Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
      socket.message({ event_type: 'task.completed' });
      jest.advanceTimersByTime(500);
    });
    expect(view.invalidate).not.toHaveBeenCalled();
    act(() => {
      Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
      document.dispatchEvent(new Event('visibilitychange'));
      jest.advanceTimersByTime(500);
    });
    expect(view.invalidate).toHaveBeenCalledWith({ queryKey: ['tasks'] }, { cancelRefetch: false });
    expect(socket.send).toHaveBeenLastCalledWith(JSON.stringify({ type: 'ping' }));
  });
  it('ignores malformed/control messages and releases sockets, batches and timers on unmount', () => {
    const view = mount();
    const socket = authenticate();
    view.invalidate.mockClear();
    act(() => {
      for (const value of [null, [], 3, { type: 'unknown' }]) socket.message(value);
      socket.onmessage?.({ data: 'invalid JSON' } as MessageEvent);
      socket.message({ event_type: 'device.offline' });
    });
    view.unmount();
    act(() => jest.advanceTimersByTime(120_000));
    expect(view.invalidate).not.toHaveBeenCalled();
    expect(socket.close).toHaveBeenCalledTimes(1);
    expect(TestWebSocket.instances).toHaveLength(1);
  });
});
