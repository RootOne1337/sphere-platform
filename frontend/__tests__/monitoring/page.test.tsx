import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
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
          details: { probe: 'HTTP request served' },
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
          cpu: null, ram: null, disk: null, status: 'HEALTHY', uptime: '1m', details: { probe: 'HTTP request served' },
        }] });
      }
      return Promise.resolve({ data: {
        observedAt: '2026-09-30T03:00:00Z',
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

  it('shows network rates only after two server-timestamped counter samples', async () => {
    const firstSample = {
      observedAt: '2026-09-29T10:00:00.000Z',
      network: { txTotalBytes: 1000, rxTotalBytes: 2000, activeTunnels: null },
    };
    jest.mocked(api.get).mockImplementation((url) => {
      if (url.endsWith('/nodes')) return Promise.resolve({ data: [] });
      return Promise.resolve({ data: firstSample });
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MonitoringPage /></QueryClientProvider>);

    expect(await screen.findByText('1000 B')).toBeInTheDocument();
    expect(screen.getByText(/Ожидаем второй замер/)).toBeInTheDocument();
    expect(screen.getByText('TX всего').parentElement).toHaveTextContent('1000 B');
    expect(screen.queryByText('0 B/s')).not.toBeInTheDocument();

    await act(async () => {
      client.setQueryData(['monitoring-metrics'], {
        observedAt: '2026-09-29T10:00:10.000Z',
        network: { txTotalBytes: 2000, rxTotalBytes: 2500, activeTunnels: null },
      });
    });

    expect(await screen.findByText('2.0 KB')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('TX / с').parentElement).toHaveTextContent('100 B/s'));
    expect(screen.getByText('RX / с').parentElement).toHaveTextContent('50 B/s');
    expect(screen.getByText(/Среднее за 10 с/)).toBeInTheDocument();
    expect(screen.getByText(/Срез API: 10:00:10 UTC/)).toBeInTheDocument();
  });

  it('does not present cached network totals as current after a metrics request fails', async () => {
    jest.mocked(api.get).mockImplementation((url) => {
      if (url.endsWith('/nodes')) return Promise.resolve({ data: [] });
      return Promise.resolve({ data: {
        observedAt: '2026-09-29T10:00:00.000Z',
        network: { txTotalBytes: 123, rxTotalBytes: 456, activeTunnels: null },
      } });
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MonitoringPage /></QueryClientProvider>);
    expect(await screen.findByText('123 B')).toBeInTheDocument();

    jest.mocked(api.get).mockRejectedValue(new Error('metrics endpoint unavailable'));
    await act(async () => {
      await client.refetchQueries({ queryKey: ['monitoring-metrics'] });
    });

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(client.getQueryState(['monitoring-metrics'])?.status).toBe('error'));
    await waitFor(() => expect(screen.getByText('TX всего').parentElement).toHaveTextContent('Недоступно'));
    expect(screen.getByText('TX всего').parentElement).toHaveTextContent('Недоступно');
    expect(screen.getByText('RX всего').parentElement).toHaveTextContent('Недоступно');
    expect(screen.getByText(/Скорость недоступна: API не вернул свежий замер/)).toBeInTheDocument();
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

  it('does not display legacy synthetic history, tunnel count or worker health without measurement provenance', async () => {
    jest.mocked(api.get).mockImplementation((url) => Promise.resolve({ data: url.endsWith('/nodes') ? [{
      id: 'task-worker-1', name: 'Task Worker', type: 'WORKER', status: 'HEALTHY', uptime: '13h 45m',
    }] : {
      cpu: { history: Array(12).fill(42) }, ram: { history: Array(8).fill(8) },
      network: { activeTunnels: 0 },
    } }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MonitoringPage /></QueryClientProvider>);
    await screen.findByText('Статус недоступен');
    expect(screen.queryByText('Task Worker')).not.toBeInTheDocument();
    expect(screen.queryByText('0 активны')).not.toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /Последние 12 измерений/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Старый monitoring payload/)).toBeInTheDocument();
  });
});
