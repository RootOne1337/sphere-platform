export type CoverageState = 'ready' | 'unavailable' | 'forbidden' | 'limited' | 'unmeasured';
export type CoverageKey = 'inventory' | 'presence' | 'android_vpn' | 'vpn_assignment' | 'handshakes' | 'transport_tunnels';
export interface CoverageSignal {
    state: CoverageState;
    source: string;
    observed_at: string | null;
    counts: Record<string, number> | null;
    reason: string;
    max_age_seconds: number | null;
}
export interface FleetCoverageSnapshot {
    schema_version: 1;
    scope: 'current-tenant-active-inventory';
    org_id: string;
    generated_at: string;
    max_inventory_devices: number;
    inventory: CoverageSignal;
    presence: CoverageSignal;
    android_vpn: CoverageSignal;
    vpn_assignment: CoverageSignal;
    handshakes: CoverageSignal;
    transport_tunnels: CoverageSignal;
}
export const COVERAGE_FIELDS: Record<CoverageKey, string[]> = {
    inventory: ['total'],
    presence: ['online', 'busy', 'connecting', 'offline', 'error', 'unknown'],
    android_vpn: ['active', 'inactive', 'stale', 'unknown'],
    vpn_assignment: ['free', 'assigned', 'error', 'provisioning', 'revoking', 'outside_active_inventory'],
    handshakes: ['recent', 'stale', 'unknown', 'inactive'],
    transport_tunnels: [],
};
const SOURCES: Record<CoverageKey, string> = {
    inventory: 'sql-active-inventory', presence: 'redis-presence', android_vpn: 'android-managed-vpn-report',
    vpn_assignment: 'sql-tenant-peers', handshakes: 'retained-sql-handshakes', transport_tunnels: 'transport-tunnel-probes',
};

/** Reject old, cross-session, contradictory or malformed snapshots before caching. */
export function parseFleetCoverage(payload: unknown, orgId: string): FleetCoverageSnapshot {
    if (!payload || typeof payload !== 'object') throw new Error('Некорректный срез покрытия');
    const data = payload as FleetCoverageSnapshot;
    if (data.schema_version !== 1 || data.scope !== 'current-tenant-active-inventory' || data.org_id !== orgId
        || !Number.isFinite(Date.parse(data.generated_at)) || !Number.isSafeInteger(data.max_inventory_devices) || data.max_inventory_devices < 1) {
        throw new Error('Срез не соответствует текущей организации или версии API');
    }
    if (data.transport_tunnels.state !== 'unmeasured') throw new Error('Проверки публичного транспорта ещё не подключены');
    for (const key of Object.keys(COVERAGE_FIELDS) as CoverageKey[]) {
        const signal = data[key];
        if (!signal || signal.source !== SOURCES[key] || typeof signal.reason !== 'string'
            || !['ready', 'unavailable', 'forbidden', 'limited', 'unmeasured'].includes(signal.state)) {
            throw new Error('Источник покрытия не подтверждён');
        }
        if (signal.state === 'ready') {
            if (!signal.counts || !Number.isFinite(Date.parse(signal.observed_at ?? ''))
                || COVERAGE_FIELDS[key].some(field => !Number.isSafeInteger(signal.counts?.[field]) || signal.counts![field] < 0)) {
                throw new Error('Измеренные значения покрытия некорректны');
            }
            const epoch = Date.parse(signal.observed_at!);
            if (epoch > Date.parse(data.generated_at) || Date.parse(data.generated_at) - epoch > 15_000) throw new Error('Время источника некорректно');
        } else if (signal.counts !== null || signal.observed_at !== null) {
            throw new Error('Неизмеренные значения не должны выглядеть актуальными');
        }
    }
    if (data.presence.state === 'ready' && data.inventory.state === 'ready') {
        const total = COVERAGE_FIELDS.presence.reduce((sum, key) => sum + data.presence.counts![key], 0);
        if (total !== data.inventory.counts!.total) throw new Error('Покрытие presence не соответствует инвентарю');
    }
    if (data.android_vpn.state === 'ready' && data.inventory.state === 'ready') {
        const total = COVERAGE_FIELDS.android_vpn.reduce((sum, key) => sum + data.android_vpn.counts![key], 0);
        if (total !== data.inventory.counts!.total) throw new Error('Покрытие Android не соответствует инвентарю');
    }
    if (data.presence.state === 'ready' && data.presence.max_age_seconds !== 120) throw new Error('Неизвестный срок presence');
    if (data.android_vpn.state === 'ready' && data.android_vpn.max_age_seconds !== 120) throw new Error('Неизвестный срок Android-наблюдения');
    if (data.handshakes.state === 'ready' && data.handshakes.max_age_seconds !== 180) throw new Error('Неизвестный срок handshake');
    return data;
}
