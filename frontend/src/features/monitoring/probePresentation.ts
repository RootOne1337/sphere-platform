import type { ClusterNode } from './monitoringTypes';

export interface ProbeDetail {
    label: string;
    value: string;
}

const sources: Partial<Record<ClusterNode['type'], string>> = {
    API: 'Выполнение текущего HTTP-запроса backend. Не проверка Android или очереди заданий.',
    DB: 'SELECT 1 и пул соединений отвечающего API-процесса. Это не весь кластер PostgreSQL.',
    CACHE: 'PING и INFO memory на Redis, к которому подключён backend.',
    DISK: 'Filesystem / внутри backend. Это не свободное место Windows-станции или Android.',
};

export function probeSource(node: ClusterNode): string {
    return sources[node.type] ?? 'Источник: проверка сервиса в backend API.';
}

export function hasProbeError(node: ClusterNode): boolean {
    return typeof node.details?.error === 'string';
}

export function probeLatency(node: ClusterNode): number | null {
    const latency = node.latencyMs;
    if (typeof latency !== 'number' || !Number.isFinite(latency) || latency < 0) return null;
    // HealthService also uses zero when no timing was obtained (timeout/initialization).
    if (latency === 0 && hasProbeError(node)) return null;
    return latency;
}

/** Project only the documented scalar fields; never render arbitrary backend details or errors. */
export function probeDetails(node: ClusterNode): ProbeDetail[] {
    const details = node.details ?? {};
    const rows: ProbeDetail[] = [];
    const numeric = (key: string, label: string, suffix = '', integer = false, maximum = Infinity) => {
        const value = details[key];
        if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > maximum
            || (integer && !Number.isSafeInteger(value))) return;
        rows.push({ label, value: `${value}${suffix}` });
    };
    if (node.type === 'API' && details.probe === 'HTTP request served') {
        rows.push({ label: 'Результат', value: 'HTTP-запрос выполнен' });
    }
    if (node.type === 'DB') {
        numeric('pool_size', 'Размер пула API-процесса', '', true);
        numeric('checked_out', 'Занято соединений', '', true);
    }
    if (node.type === 'CACHE') {
        if (typeof details.pong === 'boolean') rows.push({ label: 'Ответ PING', value: details.pong ? 'Получен' : 'Не получен' });
        numeric('used_memory_mb', 'Память Redis', ' MiB');
        // Older health INFO memory may synthesize connected_clients=0; use the
        // separate monitoring metrics card (INFO clients) until that producer is fixed.
    }
    if (node.type === 'DISK') {
        numeric('free_gb', 'Свободно', ' GiB');
        numeric('total_gb', 'Объём', ' GiB');
        numeric('usage_percent', 'Занято', '%', false, 100);
    }
    return rows;
}
