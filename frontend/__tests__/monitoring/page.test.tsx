import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import MonitoringPage from '@/app/(dashboard)/monitoring/page';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));

describe('Infrastructure Monitoring page failure states', () => {
  beforeEach(() => {
    jest.mocked(api.get).mockRejectedValue(new Error('monitoring API unavailable'));
  });

  afterEach(() => jest.clearAllMocks());

  it('does not show healthy or zero telemetry when monitoring APIs fail', async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={client}>
        <MonitoringPage />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText('STATUS UNAVAILABLE')).toBeInTheDocument());
    expect(screen.getByRole('alert')).toHaveTextContent('No healthy status is inferred');
    expect(screen.queryByText('ALL OBSERVED CHECKS HEALTHY')).not.toBeInTheDocument();
    expect(screen.queryByText('0 Mbps')).not.toBeInTheDocument();
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0);
  });

  it('shows degraded telemetry when metrics fail but verified health probes pass', async () => {
    jest.mocked(api.get).mockImplementation((url) => {
      if (url.endsWith('/nodes')) {
        return Promise.resolve({ data: [{
          id: 'backend-api-responder-1',
          name: 'Backend API responder',
          type: 'API',
          cpu: null,
          ram: null,
          disk: null,
          status: 'HEALTHY',
          uptime: '1m',
        }] });
      }
      return Promise.reject(new Error('metrics endpoint unavailable'));
    });

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MonitoringPage />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText('HEALTH CHECKS PASS · TELEMETRY DEGRADED')).toBeInTheDocument());
    expect(screen.getAllByText(/Metric request failed/)).toHaveLength(2);
  });
});
