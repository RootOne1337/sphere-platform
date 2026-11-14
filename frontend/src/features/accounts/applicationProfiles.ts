import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';

export interface ApplicationServer { key: string; name: string; domain: string; port: number }
export interface ApplicationProfile {
  id: string; key: string; name: string; android_package: string | null; aliases: string[];
  servers: ApplicationServer[]; source: 'builtin' | 'tenant'; created_at: string | null; updated_at: string | null;
}

export const MAX_APPLICATION_SERVERS = 100;
export const MAX_APPLICATION_NAME = 120;
export const MAX_ANDROID_PACKAGE = 255;
const ANDROID_PACKAGE = /^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$/;
const PROFILE_KEY = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const HOST_LABEL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i;

export function validProfileKey(value: unknown): value is string {
  return typeof value === 'string' && PROFILE_KEY.test(value);
}

export function validAndroidPackage(value: string): boolean {
  return value.length <= MAX_ANDROID_PACKAGE && ANDROID_PACKAGE.test(value);
}

export function validApplicationServer(value: unknown): value is ApplicationServer {
  const server = value as Partial<ApplicationServer> | null;
  return Boolean(server && validProfileKey(server.key) && typeof server.name === 'string' && server.name.trim()
    && server.name.length <= 50 && typeof server.domain === 'string' && server.domain.replace(/\.$/, '').length <= 253
    && server.domain.replace(/\.$/, '').split('.').every(label => HOST_LABEL.test(label))
    && Number.isInteger(server.port) && server.port! >= 1 && server.port! <= 65535);
}

export function parseApplicationProfile(value: unknown): ApplicationProfile {
  const profile = value as Partial<ApplicationProfile> | null;
  if (!profile || typeof profile.id !== 'string' || !profile.id || !validProfileKey(profile.key)
    || typeof profile.name !== 'string' || !profile.name.trim() || profile.name.length > MAX_APPLICATION_NAME
    || !(profile.android_package === null || typeof profile.android_package === 'string' && validAndroidPackage(profile.android_package))
    || !Array.isArray(profile.aliases) || !profile.aliases.every(alias => typeof alias === 'string' && alias.length <= 100)
    || !Array.isArray(profile.servers) || profile.servers.length > MAX_APPLICATION_SERVERS || !profile.servers.every(validApplicationServer)
    || !(profile.source === 'builtin' || profile.source === 'tenant')
    || !(profile.updated_at === null && profile.source === 'builtin' || typeof profile.updated_at === 'string' && Number.isFinite(Date.parse(profile.updated_at)))) {
    throw new Error('Не удалось подтвердить ответ каталога приложений.');
  }
  return profile as ApplicationProfile;
}

export function useApplicationProfiles(enabled = true) {
  const user = useAuthStore(state => state.user);
  const session = useAuthStore(state => state.sessionVersion);
  return useQuery({
    queryKey: ['application-profiles', user?.org_id, user?.id, session],
    enabled: enabled && Boolean(user),
    queryFn: async ({ signal }) => {
      const { data } = await api.get<{ items?: unknown; total?: unknown }>('/application-profiles', { signal });
      if (!Array.isArray(data?.items) || data.items.length > 100 || data.total !== data.items.length) throw new Error('Некорректный каталог приложений.');
      const items = data.items.map(parseApplicationProfile);
      if (new Set(items.map(profile => profile.key)).size !== items.length) throw new Error('Ключи каталога приложений повторяются.');
      return items;
    },
  });
}

export function findApplication(profiles: readonly ApplicationProfile[], value: string) {
  return profiles.find(profile => profile.key === value || profile.aliases.includes(value));
}

export function applicationLabel(profiles: readonly ApplicationProfile[], value: string): string {
  const profile = findApplication(profiles, value);
  return profile ? `${profile.name} · ${value}` : value;
}
