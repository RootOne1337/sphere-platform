'use client';
import { useState, useCallback } from 'react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { useDevices } from '@/lib/hooks/useDevices';

const GRID_SIZES = [1, 2, 4, 6, 9] as const;

export default function FleetStreamPage() {
  const [gridSize, setGridSize] = useState<(typeof GRID_SIZES)[number]>(4);
  // Set of device IDs that have an active stream
  const [activeStreams, setActiveStreams] = useState<Set<string>>(new Set());
  const { data } = useDevices({ status: 'online', page_size: 9 });
  const devices = data?.items ?? [];

  const cols = gridSize <= 2 ? gridSize : gridSize <= 4 ? 2 : 3;

  const startStream = useCallback((deviceId: string) => {
    setActiveStreams((prev) => new Set([...prev, deviceId]));
  }, []);

  const stopStream = useCallback((deviceId: string) => {
    setActiveStreams((prev) => {
      const next = new Set(prev);
      next.delete(deviceId);
      return next;
    });
  }, []);

  return (
    <div className="p-4 space-y-4">
      <div className="flex gap-2 items-center flex-wrap">
        <span className="text-sm text-muted-foreground">Grid:</span>
        {GRID_SIZES.map((s) => (
          <button
            key={s}
            onClick={() => setGridSize(s)}
            className={`px-2 py-1 rounded text-sm ${
              gridSize === s ? 'bg-primary text-primary-foreground' : 'bg-secondary'
            }`}
          >
            {s}x
          </button>
        ))}
        {activeStreams.size > 0 && (
          <button
            onClick={() => setActiveStreams(new Set())}
            className="ml-auto px-3 py-1 rounded text-sm bg-destructive text-destructive-foreground"
          >
            Stop All
          </button>
        )}
      </div>

      {devices.length === 0 && (
        <p className="text-sm text-muted-foreground">No online devices found.</p>
      )}

      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
      >
        {devices.slice(0, gridSize).map((device) => {
          const isActive = activeStreams.has(device.id);
          return (
            <div key={device.id} className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground truncate flex-1" title={device.name}>
                  {device.name}
                </p>
                {isActive ? (
                  <button
                    onClick={() => stopStream(device.id)}
                    className="shrink-0 px-2 py-0.5 rounded text-xs bg-destructive text-destructive-foreground"
                  >
                    Stop
                  </button>
                ) : (
                  <button
                    onClick={() => startStream(device.id)}
                    className="shrink-0 px-2 py-0.5 rounded text-xs bg-primary text-primary-foreground"
                  >
                    Start
                  </button>
                )}
              </div>
              {isActive ? (
                <DeviceStream deviceId={device.id} />
              ) : (
                <div className="rounded border border-gray-700 bg-black flex items-center justify-center text-xs text-gray-500"
                  style={{ aspectRatio: '9/16' }}>
                  Нажми Start для начала стрима
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
