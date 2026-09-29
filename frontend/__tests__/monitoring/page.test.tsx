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

      await waitFor(() => expect(screen.getByText('Статус недоступен')).toBeInTheDocument());
    expect(screen.getAllByRole('alert')[1]).toHaveTextContent('Статус здоровья не выводится из ошибки запроса');
    expect(screen.queryByText('Все полученные проверки в норме')).not.toBeInTheDocument();
    expect(screen.queryByText('0 Mbps')).not.toBeInTheDocument();
    expect(screen.getAllByText('Недоступно').length).toBeGreaterThan(0);
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

    await waitFor(() => expect(screen.getByText('Проверки прошли · метрики частично недоступны')).toBeInTheDocument());
    expect(screen.getAllByText(/Запрос метрик завершился ошибкой/)).toHaveLength(2);
  });

  it('does not present healthy dependency probes as complete telemetry when fields are null', async () => {
    jest.mocked(api.get).mockImplementation((url) => {
      if (url.endsWith('/nodes')) {
        return Promise.resolve({ data: [{
          id: 'backend-api-responder-1', name: 'Backend API responder', type: 'API',
          cpu: null, ram: null, disk: null, status: 'HEALTHY', uptime: '1m',
        }] });
      }
      return Promise.resolve({ data: {
        cpu: { linuxLoad1mPerCpu: 0.25, history: [] },
        ram: { currentBytes: 1024, totalBytes: null, history: [] },
        redis: { status: 'HEALTHY', ops: null, memory: null, clients: null },
        network: { txTotalBytes: 100, rxTotalBytes: 200, activeTunnels: null },
      } });
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MonitoringPage /></QueryClientProvider>);

    expect(await screen.findByText('Проверки прошли · метрики частично недоступны')).toBeInTheDocument();
    expect(screen.getByText(/Проверки сервисов и покрытие метрик — разные сигналы\./).parentElement).toHaveTextContent('история CPU, история памяти');
    expect(screen.getAllByText('HEALTHY').length).toBeGreaterThan(0);
  });

  it('fails safely when the monitoring nodes endpoint returns an unexpected envelope', async () => {
    jest.mocked(api.get).mockImplementation((url) => {
      if (url.endsWith('/nodes')) return Promise.resolve({ data: { nodes: [] } });
      return Promise.resolve({ data: {} });
    });

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MonitoringPage />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText('Статус недоступен')).toBeInTheDocument());
    expect(screen.getAllByRole('alert').some((alert) => alert.textContent?.includes('пришёл некорректный ответ'))).toBe(true);
    expect(screen.queryByText('Все полученные проверки в норме')).not.toBeInTheDocument();
  });
});
