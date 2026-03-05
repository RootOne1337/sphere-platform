/**
 * Тесты хука useDebounce — задержка обновления значения.
 * Покрытие: стандартная задержка, кастомная задержка, сброс таймера при быстром вводе.
 */
import { renderHook, act } from '@testing-library/react';
import { useDebounce } from '@/lib/hooks/useDebounce';

// Используем fake timers для контроля setTimeout
beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

describe('useDebounce', () => {
  it('возвращает начальное значение сразу', () => {
    const { result } = renderHook(() => useDebounce('hello'));
    expect(result.current).toBe('hello');
  });

  it('не обновляет значение до истечения задержки', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebounce(value, 300),
      { initialProps: { value: 'a' } },
    );

    rerender({ value: 'ab' });

    // 100мс — значение ещё старое
    act(() => { jest.advanceTimersByTime(100); });
    expect(result.current).toBe('a');
  });

  it('обновляет значение через 300мс (по умолчанию)', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebounce(value, 300),
      { initialProps: { value: 'a' } },
    );

    rerender({ value: 'abc' });

    act(() => { jest.advanceTimersByTime(300); });
    expect(result.current).toBe('abc');
  });

  it('поддерживает кастомную задержку', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebounce(value, 500),
      { initialProps: { value: 'x' } },
    );

    rerender({ value: 'xyz' });

    act(() => { jest.advanceTimersByTime(300); });
    expect(result.current).toBe('x'); // ещё рано

    act(() => { jest.advanceTimersByTime(200); });
    expect(result.current).toBe('xyz'); // 500мс прошло
  });

  it('сбрасывает таймер при каждом изменении (debounce-эффект)', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebounce(value, 300),
      { initialProps: { value: '' } },
    );

    // Быстрый ввод — каждая буква через 100мс
    rerender({ value: 'a' });
    act(() => { jest.advanceTimersByTime(100); });

    rerender({ value: 'ab' });
    act(() => { jest.advanceTimersByTime(100); });

    rerender({ value: 'abc' });
    act(() => { jest.advanceTimersByTime(100); });

    // Прошло 300мс с начала, но только 100мс с последнего изменения
    expect(result.current).toBe('');

    // Ещё 200мс = 300мс с последнего изменения → обновление
    act(() => { jest.advanceTimersByTime(200); });
    expect(result.current).toBe('abc');
  });

  it('работает с числовыми значениями', () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebounce(value, 200),
      { initialProps: { value: 0 } },
    );

    rerender({ value: 42 });
    act(() => { jest.advanceTimersByTime(200); });
    expect(result.current).toBe(42);
  });

  it('работает с объектами', () => {
    const initial = { page: 1 };
    const updated = { page: 2 };

    const { result, rerender } = renderHook(
      ({ value }) => useDebounce(value, 300),
      { initialProps: { value: initial } },
    );

    rerender({ value: updated });
    act(() => { jest.advanceTimersByTime(300); });
    expect(result.current).toEqual({ page: 2 });
  });
});
