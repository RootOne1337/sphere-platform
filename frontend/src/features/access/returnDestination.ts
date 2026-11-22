import { ROUTE_PERMISSIONS } from './routeAccess';

const RETURN_KEY = 'sphere-login-return';
const MAX_AGE_MS = 30 * 60 * 1000;
let inMemoryReturn: { path: string; expiresAt: number } | null = null;
const OBJECT_ID = /^[A-Za-z0-9_-]{1,128}$/;
const REQUEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;
const DETAIL_ROUTE = /^\/(devices|stream|tasks)\/[A-Za-z0-9_-]{1,128}$/;
const QUERY_RULES: Record<string, Record<string, RegExp>> = {
  '/devices': { group_id: OBJECT_ID, location_id: OBJECT_ID },
  '/stream/:id': { teach: /^1$/ },
  '/tasks': { batch_id: OBJECT_ID, view: /^batches$/, device_id: OBJECT_ID, script_id: OBJECT_ID },
  '/tasks/:id': { tab: /^logs$/ },
  '/orchestration': { run_id: OBJECT_ID, batch_id: OBJECT_ID },
  '/scripts/builder': { id: OBJECT_ID },
  '/logs': { device_id: OBJECT_ID, date: /^\d{4}-\d{2}-\d{2}$/ },
  '/audit': { request_id: REQUEST_ID },
};

export function normalizeReturnDestination(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 2048 || !value.startsWith('/')) return null;
  const hash = value.indexOf('#');
  const fragmentless = hash === -1 ? value : value.slice(0, hash);
  const queryIndex = fragmentless.indexOf('?');
  const path = queryIndex === -1 ? fragmentless : fragmentless.slice(0, queryIndex);
  const detail = DETAIL_ROUTE.exec(path);
  if (!detail && !Object.hasOwn(ROUTE_PERMISSIONS, path)) return null;

  const route = detail ? `/${detail[1]}/:id` : path;
  const rules = QUERY_RULES[route];
  if (!rules || queryIndex === -1) return path;
  const input = new URLSearchParams(fragmentless.slice(queryIndex + 1));
  const output = new URLSearchParams();
  for (const [key, validator] of Object.entries(rules)) {
    const values = input.getAll(key);
    if (values.length === 1 && validator.test(values[0])) output.set(key, values[0]);
  }
  const search = output.toString();
  return search ? `${path}?${search}` : path;
}

export function rememberReturnDestination(value: string) {
  const path = normalizeReturnDestination(value);
  inMemoryReturn = path ? { path, expiresAt: Date.now() + MAX_AGE_MS } : null;
  try {
    if (inMemoryReturn) sessionStorage.setItem(RETURN_KEY, JSON.stringify(inMemoryReturn));
    else sessionStorage.removeItem(RETURN_KEY);
  } catch { /* Browser storage may be unavailable. */ }
}

export function readReturnDestination(): string | null {
  try {
    const value = sessionStorage.getItem(RETURN_KEY);
    return value && value.length <= 2300 ? freshReturn(JSON.parse(value)) : null;
  } catch { return freshReturn(inMemoryReturn); }
}

function freshReturn(value: { path?: unknown; expiresAt?: unknown } | null): string | null {
  const now = Date.now();
  if (!value || typeof value.expiresAt !== 'number' || !Number.isFinite(value.expiresAt)
    || value.expiresAt <= now || value.expiresAt > now + MAX_AGE_MS) return null;
  return normalizeReturnDestination(value.path);
}

export function clearReturnDestination() {
  inMemoryReturn = null;
  try { sessionStorage.removeItem(RETURN_KEY); } catch { /* Browser storage may be unavailable. */ }
}
