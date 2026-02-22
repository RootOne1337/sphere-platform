'use client';
import { DeviceStream } from '@/components/sphere/DeviceStream';

interface Props {
  params: { id: string };
}

export default function DeviceStreamPage({ params }: Props) {
  return (
    <div className="p-4 space-y-4">
      <h1 className="text-xl font-bold">Remote View — {params.id}</h1>
      <div className="max-w-sm">
        <DeviceStream deviceId={params.id} width={720} height={1280} />
      </div>
    </div>
  );
}
