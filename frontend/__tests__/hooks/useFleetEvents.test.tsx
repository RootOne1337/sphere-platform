import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactNode } from 'react';
import { useAuthStore } from '@/lib/store';
import { useFleetEvents } from '@/lib/hooks/useFleetEvents';

class TestWebSocket {
  static instances: TestWebSocket[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {
    TestWebSocket.instances.push(this);
  }

  send(_data: string) {}
  close() {}
}

describe('useFleetEvents', () => {
  const originalWebSocket = global.WebSocket;

  beforeEach(() => {
    jest.useFakeTimers();
    TestWebSocket.instances = [];
    global.WebSocket = TestWebSocket as unknown as typeof WebSocket;
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

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['devices'] });
  });
});
