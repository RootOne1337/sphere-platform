/**
 * Тесты хуков VPN — назначение, отзыв, ротация, kill switch, запросы пиров.
 * Покрытие: useVpnPeers, usePoolStats, useVpnHealth, useAssignVpn, useRevokeVpn,
 * useVpnRotate, useVpnKillSwitch.
 */
import { waitFor } from '@testing-library/react';
import { renderQueryHook } from '../helpers';
import {
  useVpnPeers,
  usePoolStats,
  useVpnHealth,
  useAssignVpn,
  useRevokeVpn,
  useVpnRotate,
  useVpnKillSwitch,
} from '@/lib/hooks/useVpn';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    delete: jest.fn(),
  },
}));

const mockApi = api as jest.Mocked<typeof api>;

const MOCK_PEERS = [
  {
    id: 'vpn-001',
    device_id: 'dev-001',
    device_name: 'Pixel 7',
    assigned_ip: '10.8.0.2',
    status: 'active' as const,
    last_handshake: '2026-03-04T10:00:00Z',
  },
  {
    id: 'vpn-002',
    device_id: 'dev-002',
    device_name: 'Samsung S24',
    assigned_ip: '10.8.0.3',
    status: 'inactive' as const,
    last_handshake: null,
  },
];

const MOCK_POOL_STATS = {
  total_ips: 254,
  allocated: 12,
  free: 242,
  active_tunnels: 8,
  stale_handshakes: 2,
};

const MOCK_HEALTH = {
  status: 'healthy',
  checks: {
    wireguard: { status: 'ok' },
    ip_pool: { status: 'ok' },
    dns: { status: 'warning', detail: 'DNS resolution slow' },
  },
};

describe('useVpnPeers', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает список VPN-пиров', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_PEERS });

    const { result } = renderQueryHook(() => useVpnPeers());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
    expect(result.current.data?.[0].assigned_ip).toBe('10.8.0.2');
  });

  it('передаёт фильтры в параметры запроса', async () => {
    mockApi.get.mockResolvedValueOnce({ data: [MOCK_PEERS[0]] });

    renderQueryHook(() => useVpnPeers({ status: 'active', device_id: 'dev-001' }));

    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    expect(mockApi.get).toHaveBeenCalledWith('/vpn/peers', {
      params: { status: 'active', device_id: 'dev-001' },
    });
  });
});

describe('usePoolStats', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает статистику пула IP', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_POOL_STATS });

    const { result } = renderQueryHook(() => usePoolStats());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.total_ips).toBe(254);
    expect(result.current.data?.free).toBe(242);
  });
});

describe('useVpnHealth', () => {
  beforeEach(() => jest.clearAllMocks());

  it('загружает состояние здоровья VPN', async () => {
    mockApi.get.mockResolvedValueOnce({ data: MOCK_HEALTH });

    const { result } = renderQueryHook(() => useVpnHealth());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.status).toBe('healthy');
    expect(result.current.data?.checks.dns.detail).toBe('DNS resolution slow');
  });
});

describe('useAssignVpn', () => {
  beforeEach(() => jest.clearAllMocks());

  it('назначает VPN устройству с POST /vpn/assign', async () => {
    mockApi.post.mockResolvedValueOnce({ data: MOCK_PEERS[0] });

    const { result } = renderQueryHook(() => useAssignVpn());

    result.current.mutate({ device_id: 'dev-001', split_tunnel: true });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/vpn/assign', {
      device_id: 'dev-001',
      split_tunnel: true,
    });
  });

  it('назначает VPN без split_tunnel (опциональный параметр)', async () => {
    mockApi.post.mockResolvedValueOnce({ data: MOCK_PEERS[0] });

    const { result } = renderQueryHook(() => useAssignVpn());

    result.current.mutate({ device_id: 'dev-001' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/vpn/assign', { device_id: 'dev-001' });
  });
});

describe('useRevokeVpn', () => {
  beforeEach(() => jest.clearAllMocks());

  it('отзывает VPN у устройства DELETE /vpn/revoke/{id}', async () => {
    mockApi.delete.mockResolvedValueOnce({ data: null });

    const { result } = renderQueryHook(() => useRevokeVpn());

    result.current.mutate('dev-001');

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.delete).toHaveBeenCalledWith('/vpn/revoke/dev-001');
  });
});

describe('useVpnRotate', () => {
  beforeEach(() => jest.clearAllMocks());

  it('ротирует VPN-адреса для нескольких устройств', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { rotated: 3 } });

    const { result } = renderQueryHook(() => useVpnRotate());

    result.current.mutate({ device_ids: ['dev-001', 'dev-002', 'dev-003'] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/vpn/rotate', {
      device_ids: ['dev-001', 'dev-002', 'dev-003'],
    });
  });
});

describe('useVpnKillSwitch', () => {
  beforeEach(() => jest.clearAllMocks());

  it('включает kill switch на устройствах', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { updated: 2 } });

    const { result } = renderQueryHook(() => useVpnKillSwitch());

    result.current.mutate({ device_ids: ['dev-001', 'dev-002'], enabled: true });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/vpn/killswitch', {
      device_ids: ['dev-001', 'dev-002'],
      enabled: true,
    });
  });

  it('выключает kill switch', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { updated: 1 } });

    const { result } = renderQueryHook(() => useVpnKillSwitch());

    result.current.mutate({ device_ids: ['dev-001'], enabled: false });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockApi.post).toHaveBeenCalledWith('/vpn/killswitch', {
      device_ids: ['dev-001'],
      enabled: false,
    });
  });
});
