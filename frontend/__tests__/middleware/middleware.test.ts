/**
 * Тесты Next.js middleware — проверка что auth redirect отключён,
 * и все запросы проходят через NextResponse.next().
 */

// Мок NextResponse
const mockNext = jest.fn(() => ({ status: 200 }));
jest.mock('next/server', () => ({
  NextResponse: { next: mockNext },
}));

describe('middleware', () => {
  beforeEach(() => jest.clearAllMocks());

  it('пропускает все запросы через NextResponse.next()', async () => {
    // Динамический импорт после мока
    const { middleware } = await import('@/middleware');

    const mockRequest = {
      nextUrl: { pathname: '/dashboard' },
      cookies: { get: jest.fn() },
    } as any;

    middleware(mockRequest);

    expect(mockNext).toHaveBeenCalledTimes(1);
  });

  it('пропускает запросы к защищённым маршрутам (auth в client-side)', async () => {
    const { middleware } = await import('@/middleware');

    const mockRequest = {
      nextUrl: { pathname: '/settings' },
      cookies: { get: jest.fn() },
    } as any;

    middleware(mockRequest);

    expect(mockNext).toHaveBeenCalledTimes(1);
  });

  it('пропускает запросы к /login', async () => {
    const { middleware } = await import('@/middleware');

    const mockRequest = {
      nextUrl: { pathname: '/login' },
      cookies: { get: jest.fn() },
    } as any;

    middleware(mockRequest);

    expect(mockNext).toHaveBeenCalledTimes(1);
  });

  it('config.matcher исключает статику Next.js', async () => {
    const { config } = await import('@/middleware');

    expect(config.matcher).toBeDefined();
    expect(config.matcher[0]).toContain('_next/static');
    expect(config.matcher[0]).toContain('favicon.ico');
  });
});
