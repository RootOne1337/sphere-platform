import '@testing-library/jest-dom';

// ── Мок localStorage для jsdom ──────────────────────────────────────────────
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: jest.fn((key: string) => store[key] ?? null),
    setItem: jest.fn((key: string, value: string) => { store[key] = value; }),
    removeItem: jest.fn((key: string) => { delete store[key]; }),
    clear: jest.fn(() => { store = {}; }),
    get length() { return Object.keys(store).length; },
    key: jest.fn((index: number) => Object.keys(store)[index] ?? null),
  };
})();
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// ── window.location: мокается локально в тестах, где нужны редиректы ────────

// ── Подавление console.error от React Query в тестах ────────────────────────
const originalError = console.error;
beforeAll(() => {
  console.error = (...args: unknown[]) => {
    // Подавляем ожидаемые ошибки от React Query
    if (typeof args[0] === 'string' && args[0].includes('QueryClient')) return;
    originalError(...args);
  };
});
afterAll(() => { console.error = originalError; });
