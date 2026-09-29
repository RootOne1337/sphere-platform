import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { formatBuildRevision, hasBuildRevisionMismatch } from '@/src/shared/buildInfo';
import { BuildProvenance } from '@/src/shared/ui/BuildProvenance';

const originalFetch = global.fetch;

afterEach(() => {
  if (originalFetch) global.fetch = originalFetch;
  else Reflect.deleteProperty(global, 'fetch');
});

function mockFetch(implementation: () => Promise<Response>) {
  const fetchMock = jest.fn(implementation);
  Object.defineProperty(global, 'fetch', { configurable: true, writable: true, value: fetchMock });
  return fetchMock;
}

describe('build provenance', () => {
  it('shows only a short validated Git revision', () => {
    expect(formatBuildRevision('7c4d9cb6e9876543210abcdef1234567890abcde')).toBe('7c4d9cb6');
    expect(formatBuildRevision('unknown')).toBe('unknown');
    expect(formatBuildRevision('secret-token-value')).toBe('unknown');
    expect(formatBuildRevision(undefined)).toBe('unknown');
    expect(hasBuildRevisionMismatch('7c4d9cb6', '7c4d9cb6')).toBe(false);
    expect(hasBuildRevisionMismatch('7c4d9cb6', 'c51f4c3a')).toBe(true);
    expect(hasBuildRevisionMismatch('unknown', 'c51f4c3a')).toBe(false);
    expect(hasBuildRevisionMismatch('12345678aaaaaaaa1234567890abcdef12345678', '12345678bbbbbbbb1234567890abcdef12345678')).toBe(true);
  });

  it('shows the frontend and the revision reported by the API', async () => {
    const fetchMock = mockFetch(async () => ({
      ok: true,
      json: async () => ({ service: 'backend-api', revision: '7c4d9cb6e9876543210abcdef1234567890abcde' }),
    } as Response));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(<QueryClientProvider client={client}><BuildProvenance /></QueryClientProvider>);

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('API 7c4d9cb6'));
    expect(screen.getByRole('status')).toHaveTextContent('WEB unknown');
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/health/build', expect.objectContaining({ cache: 'no-store' }));
    client.clear();
  });

  it('keeps a compact frontend/backend build stamp available below desktop breakpoints', async () => {
    mockFetch(async () => ({
      ok: true,
      json: async () => ({ service: 'backend-api', revision: '7c4d9cb6e9876543210abcdef1234567890abcde' }),
    } as Response));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(<QueryClientProvider client={client}><BuildProvenance /></QueryClientProvider>);

    const stamp = await screen.findByRole('status');
    await waitFor(() => expect(stamp).toHaveTextContent('W:unknown A:7c4d9cb6'));
    expect(stamp).toHaveClass('flex');
    expect(stamp).not.toHaveClass('hidden');
    expect(stamp).toHaveAttribute('title', expect.stringContaining('Backend commit: 7c4d9cb6'));
    client.clear();
  });

  it('shows an unavailable API stamp instead of inventing a revision', async () => {
    mockFetch(async () => { throw new Error('network unavailable'); });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(<QueryClientProvider client={client}><BuildProvenance /></QueryClientProvider>);

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('API unavailable'));
    expect(screen.getByRole('status')).toHaveAttribute('title', expect.stringContaining('Это не проверка работоспособности API'));
    client.clear();
  });

  it('distinguishes a missing metadata endpoint from a failed API service', async () => {
    const fetchMock = mockFetch(async () => ({ ok: false, status: 404 } as Response));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><BuildProvenance /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('API no metadata'));
    expect(screen.getByRole('status')).toHaveAttribute('title', expect.stringContaining('HTTP 404'));
    expect(screen.getByRole('status')).not.toHaveTextContent('MISMATCH');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    client.clear();
  });

  it.each([503, 403])('does not treat HTTP %s as a missing metadata endpoint', async (status) => {
    const fetchMock = mockFetch(async () => ({ ok: false, status } as Response));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><BuildProvenance /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('API unavailable'));
    expect(screen.getByRole('status')).not.toHaveTextContent('no metadata');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    client.clear();
  });
});
