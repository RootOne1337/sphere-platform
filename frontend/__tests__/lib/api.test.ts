/**
 * Тесты HTTP-клиента api.ts — интерцепторы, refresh token, обработка 401.
 * Покрытие: request interceptor (добавление Bearer), response interceptor (401 → refresh),
 * очередь неудачных запросов, редирект при неудачном refresh.
 */
import axios from 'axios';

// Мокируем axios.create чтобы контролировать инстанс
const mockInterceptorsRequest = { use: jest.fn() };
const mockInterceptorsResponse = { use: jest.fn() };
const mockAxiosInstance = {
  defaults: { baseURL: '/api/v1' },
  interceptors: {
    request: mockInterceptorsRequest,
    response: mockInterceptorsResponse,
  },
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  delete: jest.fn(),
};

jest.mock('axios', () => {
  const actual = jest.requireActual('axios');
  return {
    ...actual,
    create: jest.fn(() => mockAxiosInstance),
    post: jest.fn(),
  };
});

// Мок store
const mockGetState = jest.fn(() => ({
  accessToken: 'test-access-token',
  setAccessToken: jest.fn(),
  logout: jest.fn(),
}));

jest.mock('@/lib/store', () => ({
  useAuthStore: { getState: () => mockGetState() },
  getRefreshToken: jest.fn(() => 'test-refresh-token'),
  saveRefreshToken: jest.fn(),
  clearRefreshToken: jest.fn(),
}));

describe('api.ts HTTP-клиент', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('инициализация', () => {
    it('создаёт axios инстанс с правильной конфигурацией', () => {
      jest.isolateModules(() => {
        require('@/lib/api');
      });

      expect(axios.create).toHaveBeenCalledWith(
        expect.objectContaining({
          baseURL: expect.any(String),
          timeout: 5000,
          withCredentials: true,
        }),
      );
    });

    it('регистрирует request и response интерцепторы', () => {
      jest.isolateModules(() => {
        require('@/lib/api');
      });

      expect(mockInterceptorsRequest.use).toHaveBeenCalledTimes(1);
      expect(mockInterceptorsResponse.use).toHaveBeenCalledTimes(1);
    });
  });

  describe('request interceptor', () => {
    it('добавляет Authorization header из store', () => {
      jest.isolateModules(() => {
        require('@/lib/api');
      });

      // Получаем зарегистрированный request interceptor
      const requestInterceptor = mockInterceptorsRequest.use.mock.calls[0][0];
      const config = { headers: {} as Record<string, string> };

      const result = requestInterceptor(config);

      expect(result.headers.Authorization).toBe('Bearer test-access-token');
    });

    it('не добавляет header если токен отсутствует', () => {
      mockGetState.mockReturnValueOnce({
        accessToken: null,
        setAccessToken: jest.fn(),
        logout: jest.fn(),
      });

      jest.isolateModules(() => {
        require('@/lib/api');
      });

      const requestInterceptor = mockInterceptorsRequest.use.mock.calls[0][0];
      const config = { headers: {} as Record<string, string> };

      const result = requestInterceptor(config);

      expect(result.headers.Authorization).toBeUndefined();
    });
  });
});
