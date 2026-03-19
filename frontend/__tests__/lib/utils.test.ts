/**
 * Тесты утилиты cn — мердж классов (clsx + tailwind-merge).
 * Покрытие: конкатенация, условные классы, разрешение конфликтов Tailwind.
 */
import { cn } from '@/lib/utils';

describe('cn (clsx + tailwind-merge)', () => {
  it('мерджит строковые классы', () => {
    expect(cn('px-4', 'py-2')).toBe('px-4 py-2');
  });

  it('фильтрует falsy-значения', () => {
    expect(cn('base', false && 'hidden', null, undefined, 'flex')).toBe('base flex');
  });

  it('поддерживает условные объекты', () => {
    expect(cn('base', { 'text-red-500': true, 'text-blue-500': false })).toBe('base text-red-500');
  });

  it('поддерживает массивы', () => {
    expect(cn(['px-4', 'py-2'], 'mt-1')).toBe('px-4 py-2 mt-1');
  });

  it('разрешает конфликты Tailwind (последний побеждает)', () => {
    // tailwind-merge: px-4 vs px-2 → px-2 (последний)
    expect(cn('px-4', 'px-2')).toBe('px-2');
  });

  it('разрешает конфликты цветов', () => {
    expect(cn('text-red-500', 'text-blue-500')).toBe('text-blue-500');
  });

  it('не теряет разные оси (px + py)', () => {
    expect(cn('px-4', 'py-2')).toBe('px-4 py-2');
  });

  it('возвращает пустую строку при отсутствии аргументов', () => {
    expect(cn()).toBe('');
  });

  it('корректно обрабатывает сложную комбинацию', () => {
    const result = cn(
      'base-class',
      'px-4 py-2',
      { 'bg-red-500': false, 'bg-green-500': true },
      ['rounded', 'shadow'],
      'px-6', // перезаписывает px-4
    );
    expect(result).toContain('bg-green-500');
    expect(result).not.toContain('bg-red-500');
    expect(result).toContain('px-6');
    expect(result).not.toContain('px-4');
  });
});
