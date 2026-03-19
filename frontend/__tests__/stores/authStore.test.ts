/**
 * Тесты Zustand-стора useAuthStore — управление токенами и logout.
 * Покрытие: начальное состояние, setAccessToken, setUser, logout, 
 * saveRefreshToken, getRefreshToken, clearRefreshToken.
 */
import { useAuthStore, saveRefreshToken, getRefreshToken, clearRefreshToken } from '@/lib/store';

describe('useAuthStore', () => {
  beforeEach(() => {
    // Сбрасываем состояние стора перед каждым тестом
    useAuthStore.setState({ accessToken: null, user: null });
    localStorage.clear();
  });

  describe('начальное состояние', () => {
    it('accessToken = null', () => {
      expect(useAuthStore.getState().accessToken).toBeNull();
    });

    it('user = null', () => {
      expect(useAuthStore.getState().user).toBeNull();
    });
  });

  describe('setAccessToken', () => {
    it('устанавливает токен', () => {
      useAuthStore.getState().setAccessToken('my-jwt-token');
      expect(useAuthStore.getState().accessToken).toBe('my-jwt-token');
    });

    it('перезаписывает существующий токен', () => {
      useAuthStore.getState().setAccessToken('token-1');
      useAuthStore.getState().setAccessToken('token-2');
      expect(useAuthStore.getState().accessToken).toBe('token-2');
    });
  });

  describe('setUser', () => {
    it('устанавливает пользователя', () => {
      const user = { id: 'u1', email: 'admin@sphere.io', role: 'admin', org_id: 'org-001' };
      useAuthStore.getState().setUser(user);
      expect(useAuthStore.getState().user).toEqual(user);
    });

    it('поддерживает mfa_enabled поле', () => {
      const user = { id: 'u1', email: 'a@b.c', role: 'admin', org_id: 'o1', mfa_enabled: true };
      useAuthStore.getState().setUser(user);
      expect(useAuthStore.getState().user?.mfa_enabled).toBe(true);
    });
  });

  describe('logout', () => {
    it('очищает accessToken и user', () => {
      useAuthStore.getState().setAccessToken('token');
      useAuthStore.getState().setUser({ id: 'u1', email: 'a@b.c', role: 'admin', org_id: 'o1' });

      useAuthStore.getState().logout();

      expect(useAuthStore.getState().accessToken).toBeNull();
      expect(useAuthStore.getState().user).toBeNull();
    });

    it('удаляет refresh_token из localStorage', () => {
      saveRefreshToken('refresh-123');
      expect(getRefreshToken()).toBe('refresh-123');

      useAuthStore.getState().logout();

      expect(getRefreshToken()).toBeNull();
    });
  });
});

describe('Refresh Token утилиты (localStorage)', () => {
  beforeEach(() => localStorage.clear());

  describe('saveRefreshToken', () => {
    it('сохраняет токен в localStorage', () => {
      saveRefreshToken('rt-abc');
      expect(localStorage.getItem('sphere_refresh_token')).toBe('rt-abc');
    });

    it('перезаписывает существующий', () => {
      saveRefreshToken('rt-1');
      saveRefreshToken('rt-2');
      expect(localStorage.getItem('sphere_refresh_token')).toBe('rt-2');
    });
  });

  describe('getRefreshToken', () => {
    it('возвращает токен', () => {
      localStorage.setItem('sphere_refresh_token', 'rt-xyz');
      expect(getRefreshToken()).toBe('rt-xyz');
    });

    it('возвращает null если нет токена', () => {
      expect(getRefreshToken()).toBeNull();
    });
  });

  describe('clearRefreshToken', () => {
    it('удаляет токен из localStorage', () => {
      saveRefreshToken('rt-temp');
      clearRefreshToken();
      expect(getRefreshToken()).toBeNull();
    });
  });
});
