import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export function isUtcLogDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000-')) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function useDeviceLogDates(deviceId: string, sessionVersion: number, enabled: boolean) {
  return useQuery({
    queryKey: ['device-log-dates', sessionVersion, deviceId],
    enabled,
    retry: false,
    retryOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const { data } = await api.get<{ device_id?: unknown; dates?: unknown }>(
        `/logs/${encodeURIComponent(deviceId)}/dates`, { signal },
      );
      if (data?.device_id !== deviceId || !Array.isArray(data.dates) || data.dates.length > 128
        || !data.dates.every((date, index, values) => isUtcLogDate(date) && (index === 0 || date < values[index - 1]))) {
        throw new Error('Backend вернул некорректный список дат архива.');
      }
      return data.dates as string[];
    },
  });
}
