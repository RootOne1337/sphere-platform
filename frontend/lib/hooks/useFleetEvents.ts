import { useEffect, useRef, useCallback } from 'react';
import { useAuthStore } from '@/lib/store';
import { useQueryClient } from '@tanstack/react-query';

export type FleetEventType =
  | 'device.online'
  | 'device.offline'
  | 'device.status_changed'
  | 'task.queued'
  | 'task.started'
  | 'task.progress'
  | 'task.completed'
  | 'task.failed'
  | 'vpn.assigned'
  | 'vpn.revoked'
  | 'vpn.failed'
  | 'stream.started'
  | 'stream.stopped'
  | 'alert.triggered';

export interface FleetEvent {
  type: FleetEventType;
  device_id?: string;
  task_id?: string;
  payload?: Record<string, unknown>;
  timestamp: string;
}

type EventHandler = (event: FleetEvent) => void;

const WS_RECONNECT_BASE_MS = 1000;
const WS_RECONNECT_MAX_MS = 30000;
const WS_MAX_RETRIES = Infinity; // never stop trying

export function useFleetEvents(onEvent?: EventHandler) {
  const { accessToken } = useAuthStore();
  const wsRef = useRef<WebSocket | null>(null);
  const qc = useQueryClient();
  const attemptRef = useRef(0);
  const unmountedRef = useRef(false);

  const handleMessage = useCallback(
    (evt: MessageEvent) => {
      if (typeof evt.data !== 'string') return;
      try {
        const event: FleetEvent = JSON.parse(evt.data);
        onEvent?.(event);

        // Auto-invalidate relevant queries on events
        switch (event.type) {
          case 'device.online':
          case 'device.offline':
          case 'device.status_changed':
            qc.invalidateQueries({ queryKey: ['devices'] });
            break;
          case 'task.queued':
          case 'task.started':
          case 'task.progress':
          case 'task.completed':
          case 'task.failed':
            qc.invalidateQueries({ queryKey: ['tasks'] });
            break;
          case 'vpn.assigned':
          case 'vpn.revoked':
          case 'vpn.failed':
            qc.invalidateQueries({ queryKey: ['vpn'] });
            break;
        }
      } catch {
        // ignore non-JSON messages
      }
    },
    [onEvent, qc],
  );

  useEffect(() => {
    if (!accessToken) return;
    unmountedRef.current = false;
    attemptRef.current = 0;

    let reconnectTimer: ReturnType<typeof setTimeout>;
    let currentWs: WebSocket | null = null;

    const buildWsUrl = (): string => {
      // 1) Dedicated WS env var
      const wsEnv = process.env.NEXT_PUBLIC_WS_URL;
      if (wsEnv) return wsEnv + '/ws/events';

      // 2) Derive from API URL (strip /api/... suffix, swap http→ws)
      const apiUrl = process.env.NEXT_PUBLIC_API_URL;
      if (apiUrl) {
        return apiUrl.replace(/\/api.*$/, '').replace(/^http/, 'ws') + '/ws/events';
      }

      // 3) Fallback: current origin (works when accessed via Nginx on same port)
      const origin = typeof window !== 'undefined'
        ? window.location.origin
        : 'http://localhost:8000';
      return origin.replace(/^http/, 'ws') + '/ws/events';
    };

    const connectWs = () => {
      if (unmountedRef.current) return;

      const wsUrl = buildWsUrl();
      const ws = new WebSocket(wsUrl);
      currentWs = ws;
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ token: accessToken }));
        attemptRef.current = 0; // reset backoff on success
      };

      ws.onmessage = handleMessage;

      ws.onerror = () => {
        // onclose will fire after onerror — reconnect handled there
      };

      ws.onclose = (ev) => {
        wsRef.current = null;
        currentWs = null;

        // Don't reconnect on intentional close (unmount) or auth rejection
        if (unmountedRef.current) return;
        if (ev.code === 4001) return; // invalid_token — reconnect won't help

        // Exponential backoff with jitter
        const attempt = attemptRef.current++;
        const baseDelay = Math.min(
          WS_RECONNECT_BASE_MS * Math.pow(2, attempt),
          WS_RECONNECT_MAX_MS,
        );
        const jitter = baseDelay * 0.2 * Math.random();
        const delay = baseDelay + jitter;

        reconnectTimer = setTimeout(connectWs, delay);
      };
    };

    // Defer the initial connect by one tick so React StrictMode's fake
    // mount→cleanup→remount doesn't create a WS that is immediately closed.
    reconnectTimer = setTimeout(connectWs, 0);

    return () => {
      unmountedRef.current = true;
      clearTimeout(reconnectTimer);
      if (currentWs) {
        currentWs.onclose = null; // prevent reconnect from cleanup close
        currentWs.close();
      }
    };
  }, [accessToken, handleMessage]);

  return wsRef;
}
