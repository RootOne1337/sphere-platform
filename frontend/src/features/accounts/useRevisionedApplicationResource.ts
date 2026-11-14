import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { useAuthStore } from '@/lib/store';

const WRITE_ERRORS = new Map([
  ['Application binding changed; reload before saving', 'Привязка изменилась. Перечитайте сохранённое значение.'],
  ['Device has active automation or an account session', 'У устройства есть активная задача, пайплайн или сессия аккаунта. Дождитесь завершения и перечитайте привязку.'],
  ['Server key is not in the application profile', 'Сервер отсутствует в выбранном профиле. Перечитайте каталог приложений.'],
  ['Application policy changed; reload before saving', 'Настройки профиля изменились. Перечитайте сохранённые значения.'],
  ['Android package is required to enable automation', 'Укажите Android-пакет в профиле приложения.'],
  ['An enabled operation requires a published script', 'Для включённого режима нужен опубликованный сценарий.'],
  ['Select an active published script in this organization', 'Выберите активный сценарий с опубликованной версией в этой организации.'],
]);

export function useRevisionedApplicationResource<T extends { revision: number }, D extends object>(
  path: string, parse: (value: unknown) => T, matches: (observed: T, draft: D) => boolean,
) {
  const version = useAuthStore(state => state.sessionVersion);
  const actor = useAuthStore(state => state.user);
  const cache = useQueryClient();
  const queryKey = ['application-resource', actor?.org_id, actor?.id, version, path];
  const query = useQuery({ queryKey, retry: false, queryFn: async ({ signal }) => parse((await api.get(path, { signal })).data) });
  const locked = useRef(false);
  const [pending, setPending] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(draft: D, revision: number): Promise<T | null> {
    if (locked.current || blocked || !query.isSuccess || query.isFetching || query.data.revision !== revision) return null;
    locked.current = true;
    setPending(true);
    setError(null);
    try {
      const receipt = parse((await api.put(path, { ...draft, expected_revision: revision })).data);
      if (receipt.revision <= revision || !matches(receipt, draft)) throw new Error('Invalid update receipt');
      const observed = parse((await api.get(path)).data);
      await cache.cancelQueries({ queryKey, exact: true });
      cache.setQueryData(queryKey, observed);
      if (observed.revision !== receipt.revision || !matches(observed, draft)) throw new Error('Saved revision changed before readback');
      return observed;
    } catch (failure) {
      const status = (failure as { response?: { status?: number } } | null)?.response?.status;
      if (status !== 400 && status !== 422) setBlocked(true);
      const reason = getApiErrorMessage(failure, 'Результат записи не подтверждён. Перечитайте сохранённые значения перед повтором.');
      setError(WRITE_ERRORS.get(reason) ?? reason);
      return null;
    } finally {
      locked.current = false;
      setPending(false);
    }
  }

  async function reload(): Promise<T | null> {
    const response = await query.refetch();
    if (!response.isSuccess) return null;
    setBlocked(false);
    setError(null);
    return response.data;
  }

  return { query, save, reload, pending, blocked, error };
}
