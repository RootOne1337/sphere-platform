// Diagnostic workflow fixtures. Render current source and substitute only its external inputs.
const React = require('react');
const { act, fireEvent, render, screen, waitFor } = require('@testing-library/react');
const { QueryClient, QueryClientProvider } = require('@tanstack/react-query');

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/store', () => ({ useAuthStore: select => {
  const state = { accessToken: 'synthetic-fixture', sessionVersion: 1 };
  return typeof select === 'function' ? select(state) : state;
} }));
jest.mock('@/lib/hooks/useDeviceSnapshot', () => ({ useDeviceSnapshot: () => ({ data: { id: 'audit-fixture', name: 'Fixture' } }) }));
jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: () => ({ data: { items: [] } }) }));
jest.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams('device_id=audit-fixture&date=2026-11-10'),
  useRouter: () => ({ replace: jest.fn() }),
}));
jest.mock('@/lib/h264-decoder', () => ({ H264Decoder: class { init() {} destroy() {} reset() {} } }));

const { api } = require('@/lib/api');
const LogsPage = require('@/app/(dashboard)/logs/page').default;
const { DeviceStream } = require('@/components/sphere/DeviceStream');
const { StreamSessionHistoryPanel } = require('@/src/features/stream/StreamSessionHistoryPanel');
const deviceId = 'audit-fixture';

afterEach(() => { jest.restoreAllMocks(); jest.useRealTimers(); api.get.mockReset(); });

it('sends incident search to the recent-file tail even with a date in the page URL', async () => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
  api.get.mockResolvedValue({ data: { device_id: deviceId, lines: [], total: 0 } });
  render(React.createElement(LogsPage));
  fireEvent.change(screen.getByRole('textbox', { name: 'Поиск в логах' }), { target: { value: 'isolated_archive_incident' } });
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith(
    '/logs/audit-fixture?lines=1000&search=isolated_archive_incident', expect.any(Object)
  ));
  expect(api.get.mock.calls.every(([url]) => !url.includes('date='))).toBe(true);
});

it('reports a pre-history auth timeout as an access denial and does not reconnect', () => {
  class Socket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 3;
    static instances = [];
    readyState = Socket.CONNECTING;
    send = jest.fn();
    close = jest.fn();
    constructor() { Socket.instances.push(this); }
  }
  jest.useFakeTimers();
  const originalSocket = global.WebSocket;
  global.WebSocket = Socket;
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: jest.fn() });
  const view = render(React.createElement(DeviceStream, { deviceId }));
  try {
    act(() => jest.advanceTimersByTime(0));
    act(() => Socket.instances[0].onclose({ code: 4003, reason: 'auth_timeout', wasClean: true }));
    expect(screen.getByRole('status')).toHaveTextContent('У этой учётной записи нет доступа к просмотру устройства.');
    act(() => jest.advanceTimersByTime(60_000));
    expect(Socket.instances).toHaveLength(1);
  } finally {
    view.unmount();
    global.WebSocket = originalSocket;
  }
});

it('renders simultaneous stream sessions without exposing their available correlation IDs', async () => {
  const sessions = ['1111111111111111', '2222222222222222'].map(session_id => ({
    session_id, opened_at: '2026-11-13T10:00:00Z', state: 'closed',
  }));
  api.get.mockResolvedValue({ data: { schema_version: 1, device_id: deviceId, session_limit: 10, sessions } });
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(React.createElement(QueryClientProvider, { client: query },
    React.createElement(StreamSessionHistoryPanel, { deviceId })));
  try {
    const rows = await screen.findAllByRole('listitem', { hidden: true });
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toBe(rows[1].textContent);
    for (const { session_id } of sessions) expect(view.container.innerHTML).not.toContain(session_id);
  } finally {
    view.unmount();
    query.clear();
  }
});
