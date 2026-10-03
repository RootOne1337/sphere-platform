// Routes map to the existing guards of their read/workflow endpoints. No role matrix.
export const ROUTE_PERMISSIONS: Record<string, string | null> = {
  '/dashboard': 'monitoring:read', '/monitoring': 'monitoring:read',
  '/devices': 'device:read', '/fleet': 'device:read', '/stream': 'stream:read',
  '/discovery': 'device:write', '/groups': 'device:read', '/locations': 'device:read',
  '/tasks': 'script:read', '/orchestration': 'pipeline:read',
  '/pipeline-settings': 'pipeline:read', '/accounts': 'account:read',
  '/scripts': 'script:read', '/scripts/builder': 'script:write',
  '/events': 'event:read', '/event-triggers': 'pipeline:read', '/sessions': 'session:read',
  '/vpn': 'vpn:read', '/webhooks': null, '/users': 'user:read', '/audit': 'audit:read',
  '/logs': 'device:read', '/updates': 'device:read', '/settings': null,
};

export function canAccessRoute(pathname: string, permissions: readonly string[], verified: boolean): boolean {
  if (!verified) return false;
  const path = pathname.split(/[?#]/, 1)[0].replace(/\/+$/, '') || '/dashboard';
  const route = Object.keys(ROUTE_PERMISSIONS).sort((a, b) => b.length - a.length)
    .find(key => path === key || path.startsWith(`${key}/`));
  if (!route) return false;
  const required = ROUTE_PERMISSIONS[route];
  return required === null || permissions.includes(required);
}
