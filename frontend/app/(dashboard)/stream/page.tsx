'use client';
import { useState } from 'react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { useDevices } from '@/lib/hooks/useDevices';

const GRID_SIZES = [1, 2, 4, 6, 9] as const;

export default function FleetStreamPage() {
  const [gridSize, setGridSize] = useState<(typeof GRID_SIZES)[number]>(4);
  const { data } = useDevices({ status: 'online', page_size: 9 });
  const devices = data?.items ?? [];

  const cols = gridSize <= 2 ? gridSize : gridSize <= 4 ? 2 : 3;

  return (
    <div className="p-4 space-y-4">
      <div className="flex gap-2 items-center">
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
      </div>

      <div
        className="grid gap-2"
        style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
      >
        {devices.slice(0, gridSize).map((device) => (
          <div key={device.id} className="space-y-1">
            <p className="text-xs text-muted-foreground truncate">{device.name}</p>
            <DeviceStream deviceId={device.id} width={720} height={1280} />
          </div>
        ))}
      </div>
    </div>
  );
}
