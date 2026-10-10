import '@testing-library/jest-dom';

// jsdom has no layout/media-query engine. Individual responsive tests supply
// controlled breakpoint changes; ordinary render tests use a desktop baseline.
if (typeof window !== 'undefined') Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: jest.fn((query: string) => ({
  matches: query === '(min-width: 1024px)', media: query, onchange: null,
  addEventListener: jest.fn(), removeEventListener: jest.fn(),
  addListener: jest.fn(), removeListener: jest.fn(), dispatchEvent: jest.fn(),
})) });

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
if (typeof window !== 'undefined') Object.defineProperty(window, 'localStorage', { value: localStorageMock });

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
