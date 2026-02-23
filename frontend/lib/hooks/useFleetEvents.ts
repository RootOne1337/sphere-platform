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

export function useFleetEvents(onEvent?: EventHandler) {
  const { accessToken } = useAuthStore();
  const wsRef = useRef<WebSocket | null>(null);
  const qc = useQueryClient();

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

    // WS endpoint is at /ws/events (not under /api/v1 prefix) — use page origin
    const origin = typeof window !== 'undefined'
      ? window.location.origin
      : (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost').replace(/\/api.*$/, '');
    const wsUrl = origin.replace(/^http/, 'ws') + '/ws/events';
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ token: accessToken }));
    };

    ws.onmessage = handleMessage;

    // Reconnect on close
    let reconnectTimer: ReturnType<typeof setTimeout>;
    ws.onclose = () => {
      reconnectTimer = setTimeout(() => {
        // Component will re-render via useEffect deps if token changes
      }, 5000);
    };

    return () => {
      clearTimeout(reconnectTimer);
      ws.close();
    };
  }, [accessToken, handleMessage]);

  return wsRef;
}
