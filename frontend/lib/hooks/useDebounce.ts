import { useState, useEffect } from 'react';

/**
 * Задерживает обновление значения на указанный интервал.
 * Используется для debounce поисковых запросов, чтобы не отправлять
 * HTTP-запрос на каждый введённый символ.
 *
 * @param value — исходное значение (обновляется при каждом нажатии)
 * @param delay — задержка в мс (по умолчанию 300 мс)
 * @returns debounced-значение, обновляемое после паузы ввода
 */
export function useDebounce<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
