export type VpnScopeMode = 'selected_apps' | 'all_apps_except_control';
type CommonTrafficPolicy = { control_plane: 'bypass'; ipv6: 'block' | 'tunnel' };
export type VpnTrafficPolicy = CommonTrafficPolicy & (
  { mode: 'selected_apps'; kill_switch: 'selected_apps'; included_packages: string[] }
  | { mode: 'all_apps_except_control'; kill_switch: 'all_apps_except_control' }
);

export function trafficPolicy(mode: VpnScopeMode, packages: string[], ipv6: 'block' | 'tunnel'): VpnTrafficPolicy {
  return mode === 'all_apps_except_control'
    ? { mode, control_plane: 'bypass', kill_switch: mode, ipv6 }
    : { mode, control_plane: 'bypass', kill_switch: mode, ipv6, included_packages: [...packages] };
}

function validTrafficPolicy(value: unknown): value is VpnTrafficPolicy {
  if (!value || typeof value !== 'object') return false;
  const p = value as VpnTrafficPolicy;
  if (p.control_plane !== 'bypass' || !['block', 'tunnel'].includes(p.ipv6) || p.kill_switch !== p.mode) return false;
  if (p.mode === 'all_apps_except_control') return Object.keys(p).sort().join() === 'control_plane,ipv6,kill_switch,mode';
  return p.mode === 'selected_apps' && Object.keys(p).sort().join() === 'control_plane,included_packages,ipv6,kill_switch,mode'
    && Array.isArray(p.included_packages) && p.included_packages.length >= 1 && p.included_packages.length <= 64
    && p.included_packages.every(v => typeof v === 'string');
}

export interface SavedVpnProfile {
  id: string; revision_id: string; current_revision: number; name: string; description: string;
  provider_id: 'android-amneziawg' | 'legacy-root';
  protocol: 'wireguard' | 'amneziawg'; protocol_version: string; is_archived: boolean;
  traffic_policy: VpnTrafficPolicy;
}

export interface ProfileSaveReceipt {
  profile_id: string; revision_id: string; revision: number; request_id: string;
  persisted: true; apply_allowed: false; execution_confirmed: false;
}

const uuid = (v: unknown): v is string => typeof v === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);

export function validSaveReceipt(value: unknown, requestId: string, target?: SavedVpnProfile): value is ProfileSaveReceipt {
  if (!value || typeof value !== 'object') return false;
  const r = value as ProfileSaveReceipt;
  return uuid(r.profile_id) && uuid(r.revision_id) && r.request_id === requestId
    && r.persisted === true && r.apply_allowed === false && r.execution_confirmed === false
    && r.revision === (target ? target.current_revision + 1 : 1) && (!target || r.profile_id === target.id);
}

export function parseProfilePage(value: unknown, page: number): { items: SavedVpnProfile[]; total: number } {
  if (!value || typeof value !== 'object') throw new Error('invalid_profile_page');
  const data = value as { items: SavedVpnProfile[]; page: number; page_size: number; total: number };
  if (data.page !== page || data.page_size !== 10 || !Number.isInteger(data.total) || data.total < 0
    || !Array.isArray(data.items) || data.items.length > 10 || data.total < data.items.length) throw new Error('invalid_profile_page');
  const items = data.items.map(row => {
    const p = row?.traffic_policy;
    if (!row || !uuid(row.id) || !uuid(row.revision_id) || !Number.isInteger(row.current_revision) || row.current_revision < 1
      || typeof row.name !== 'string' || !row.name || typeof row.description !== 'string'
      || !['android-amneziawg', 'legacy-root'].includes(row.provider_id)
      || !['wireguard', 'amneziawg'].includes(row.protocol) || !['1', '1.5', '2', '3.1'].includes(row.protocol_version)
      || typeof row.is_archived !== 'boolean' || !validTrafficPolicy(p)) throw new Error('invalid_profile_metadata');
    // Keep an explicit metadata projection, not arbitrary response properties.
    return { id: row.id, revision_id: row.revision_id, current_revision: row.current_revision, name: row.name, provider_id: row.provider_id,
      description: row.description, protocol: row.protocol, protocol_version: row.protocol_version, is_archived: row.is_archived,
      traffic_policy: trafficPolicy(p.mode, p.mode === 'selected_apps' ? p.included_packages : [], p.ipv6) };
  });
  if (new Set(items.map(v => v.id)).size !== items.length) throw new Error('duplicate_profiles');
  return { items, total: data.total };
}
