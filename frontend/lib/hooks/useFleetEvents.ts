import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/lib/store';
import { useQueryClient } from '@tanstack/react-query';

export type FleetEventType =
  | 'device.online' | 'device.offline' | 'device.status_change' | 'device.status_changed'
  | 'task.queued' | 'task.started' | 'task.progress' | 'task.completed' | 'task.failed'
  | 'command.started' | 'command.completed' | 'command.failed'
  | 'vpn.assigned' | 'vpn.revoked' | 'vpn.failed'
  | 'stream.started' | 'stream.stopped' | 'alert.triggered'
  | 'account.banned' | 'account.captcha' | 'account.phone_verify' | 'account.error'
  | 'account.assigned' | 'account.released' | 'account.rotated'
  | 'game.crashed' | 'session.started' | 'session.ended';

export interface FleetEvent {
  event_type: FleetEventType;
  device_id?: string;
  task_id?: string;
  payload?: Record<string, unknown>;
  ts: string;
}

export type FleetConnectionState = 'connecting' | 'live' | 'reconnecting' | 'offline' | 'unauthorized';
type EventHandler = (event: FleetEvent) => void;

// The backend supports first-message token auth, then snapshot / ping / pong.
// A browser's TCP open is not evidence of an authenticated, responsive feed.
const HEARTBEAT_INTERVAL_MS = 20_000;
const RESPONSE_TIMEOUT_MS = 10_000;
const HANDSHAKE_TIMEOUT_MS = 15_000;
const REFRESH_BATCH_MS = 500;
const LIVE_QUERY_ROOTS = [
  'devices', 'tasks', 'dashboard', 'device-events', 'vpn', 'batches',
  'pipeline-runs', 'orchestration-status', 'account-sessions', 'game-accounts', 'device-inspector', 'fleet-coverage',
  'direct-probe-capabilities',
];

function eventQueryRoots(type: string): string[] {
  if (type.startsWith('device.')) return ['devices', 'dashboard', 'device-events', 'fleet-coverage', 'direct-probe-capabilities'];
  if (type.startsWith('task.')) return ['tasks', 'devices', 'dashboard', 'batches', 'pipeline-runs', 'orchestration-status', 'device-events', 'fleet-coverage'];
  if (type.startsWith('command.')) return ['device-inspector', 'device-events'];
  if (type.startsWith('vpn.')) return ['vpn', 'devices', 'device-events', 'fleet-coverage'];
  if (type.startsWith('account.') || type.startsWith('session.')) return ['game-accounts', 'account-sessions', 'device-events'];
  if (type.startsWith('stream.') || type === 'game.crashed' || type === 'alert.triggered') return ['devices', 'device-events'];
  return [];
}

export function useFleetEvents(onEvent?: EventHandler) {
  const accessToken = useAuthStore(state => state.accessToken);
  const qc = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const handlerRef = useRef(onEvent);
  const [state, setState] = useState<FleetConnectionState>('connecting');
  useEffect(() => { handlerRef.current = onEvent; }, [onEvent]);

  useEffect(() => {
    if (!accessToken) { setState('unauthorized'); return; }
    let stopped = false;
    let rejected = false;
    let attempt = 0;
    let authenticated = false;
    let lastResponse = 0;
    let current: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let responseTimer: ReturnType<typeof setTimeout> | undefined;
    let heartbeatTimer: ReturnType<typeof setTimeout> | undefined;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    const pendingRoots = new Set<string>();

    const refresh = (roots: string[]) => {
      roots.forEach(root => pendingRoots.add(root));
      if (document.visibilityState === 'hidden') return;
      if (refreshTimer !== undefined) return;
      refreshTimer = setTimeout(() => {
        refreshTimer = undefined;
        if (document.visibilityState === 'hidden') return;
        pendingRoots.forEach(root => {
          // Mark inactive cached pages stale too, but only refetch mounted queries.
          // Keep an in-flight read: progress bursts must not repeatedly cancel it.
          void qc.invalidateQueries({ queryKey: [root] }, { cancelRefetch: false });
        });
        pendingRoots.clear();
      }, REFRESH_BATCH_MS);
    };
    const clearHeartbeat = () => {
      clearTimeout(responseTimer);
      clearTimeout(heartbeatTimer);
      responseTimer = heartbeatTimer = undefined;
    };
    const detach = () => {
      const ws = current;
      current = wsRef.current = null;
      if (ws) {
        ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
        ws.close();
      }
      clearHeartbeat();
    };
    const scheduleReconnect = () => {
      if (stopped || rejected) return;
      clearTimeout(reconnectTimer);
      if (!navigator.onLine) { setState('offline'); return; }
      setState('reconnecting');
      const base = Math.min(1000 * 2 ** Math.min(attempt++, 5), 30_000);
      reconnectTimer = setTimeout(connect, Math.min(base * (0.8 + Math.random() * 0.4), 30_000));
    };
    const reconnect = () => { detach(); scheduleReconnect(); };
    const ping = (ws: WebSocket) => {
      if (stopped || current !== ws || ws.readyState !== WebSocket.OPEN) return;
      clearHeartbeat();
      try { ws.send(JSON.stringify({ type: 'ping' })); }
      catch { reconnect(); return; }
      responseTimer = setTimeout(reconnect, RESPONSE_TIMEOUT_MS);
    };
    const confirm = (ws: WebSocket) => {
      lastResponse = Date.now();
      if (!authenticated) {
        authenticated = true;
        attempt = 0;
        setState('live');
        // PubSub has no replay cursor. Re-read the authoritative REST state
        // after every authenticated connection, including the first one.
        refresh(LIVE_QUERY_ROOTS);
      }
      clearHeartbeat();
      heartbeatTimer = setTimeout(() => ping(ws), HEARTBEAT_INTERVAL_MS);
    };
    function connect() {
      reconnectTimer = undefined;
      if (stopped || rejected) return;
      if (!navigator.onLine) { setState('offline'); return; }
      authenticated = false;
      lastResponse = 0;
      const wsEnv = process.env.NEXT_PUBLIC_WS_URL?.replace(/\/$/, '');
      const wsUrl = (wsEnv || window.location.origin.replace(/^http/, 'ws')) + '/ws/events';
      let ws: WebSocket;
      try { ws = new WebSocket(wsUrl); }
      catch { scheduleReconnect(); return; }
      current = wsRef.current = ws;
      responseTimer = setTimeout(reconnect, HANDSHAKE_TIMEOUT_MS);
      ws.onopen = () => {
        if (current !== ws || stopped) return;
        try {
          ws.send(JSON.stringify({ token: accessToken }));
          // Pong also confirms authorization when the initial snapshot fails.
          ws.send(JSON.stringify({ type: 'ping' }));
        } catch { reconnect(); }
      };
      ws.onmessage = (message: MessageEvent) => {
        if (current !== ws || stopped || typeof message.data !== 'string') return;
        let wire: Record<string, unknown>;
        try {
          const parsed: unknown = JSON.parse(message.data);
          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return;
          wire = parsed as Record<string, unknown>;
        } catch { return; }
        if (wire.type === 'pong' || wire.type === 'snapshot') { confirm(ws); return; }
        const type = wire.event_type ?? wire.type;
        if (typeof type !== 'string') return;
        const roots = eventQueryRoots(type);
        if (!roots.length) return;
        confirm(ws);
        refresh(roots);
        // A UI callback cannot break cache reconciliation or heartbeat handling.
        try { handlerRef.current?.({ ...wire, event_type: type as FleetEventType, ts: String(wire.ts ?? wire.timestamp ?? '') }); }
        catch { /* callback failure is isolated from the transport */ }
      };
      ws.onerror = () => { /* onclose or the bounded watchdog recovers the feed */ };
      ws.onclose = (event: CloseEvent) => {
        if (current !== ws || stopped) return;
        detach();
        if (event.code === 4001) { rejected = true; setState('unauthorized'); return; }
        scheduleReconnect();
      };
    }
    const onOffline = () => {
      clearTimeout(reconnectTimer);
      detach();
      if (!rejected) setState('offline');
    };
    const onResume = () => {
      if (stopped || rejected || !navigator.onLine || document.visibilityState === 'hidden') return;
      // Recover a frozen browser timer / silently broken socket immediately.
      if (!current || (authenticated && Date.now() - lastResponse > HEARTBEAT_INTERVAL_MS + RESPONSE_TIMEOUT_MS)) {
        clearTimeout(reconnectTimer);
        detach();
        setState('connecting');
        connect();
      } else if (authenticated && responseTimer === undefined) {
        refresh(LIVE_QUERY_ROOTS);
        ping(current);
      }
    };
    window.addEventListener('offline', onOffline);
    window.addEventListener('online', onResume);
    document.addEventListener('visibilitychange', onResume);
    // Avoid creating an abandoned socket during StrictMode's probe mount.
    setState(navigator.onLine ? 'connecting' : 'offline');
    reconnectTimer = setTimeout(connect, 0);
    return () => {
      stopped = true;
      clearTimeout(reconnectTimer);
      clearTimeout(refreshTimer);
      pendingRoots.clear();
      detach();
      window.removeEventListener('offline', onOffline);
      window.removeEventListener('online', onResume);
      document.removeEventListener('visibilitychange', onResume);
    };
  }, [accessToken, qc]);

  return { socketRef: wsRef, state };
}
