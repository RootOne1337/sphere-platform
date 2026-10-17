export const USER_ROLES = ['viewer', 'script_runner', 'device_manager', 'api_user', 'org_admin', 'org_owner', 'super_admin'] as const;
export type UserRole = (typeof USER_ROLES)[number];
export const USER_ROLE_LABELS: Record<UserRole, string> = {
  viewer: 'Наблюдатель', script_runner: 'Запуск сценариев', device_manager: 'Управление устройствами',
  api_user: 'API-пользователь', org_admin: 'Администратор', org_owner: 'Владелец организации', super_admin: 'Администратор платформы',
};

// Mirrors backend/core/rbac.py::can_manage_role. The server remains authoritative.
export function canManageUserRole(actor: string, target: string): boolean {
  if (!USER_ROLES.includes(target as UserRole)) return false;
  if (actor === 'super_admin') return true;
  if (actor === 'org_owner') return target !== 'super_admin';
  return actor === 'org_admin' && ['viewer', 'script_runner', 'device_manager', 'api_user'].includes(target);
}
export function canReadUsers(role: string): boolean { return ['org_admin', 'org_owner', 'super_admin'].includes(role); }
export function canChangeUserRole(role: string): boolean { return ['org_owner', 'super_admin'].includes(role); }
