'use client';
import { use } from 'react';
import { DeviceStream } from '@/components/sphere/DeviceStream';

interface Props {
  params: Promise<{ id: string }>;
}

export default function DeviceStreamPage({ params }: Props) {
  const { id } = use(params);
  return (
    <div className="p-4 space-y-4">
      <h1 className="text-xl font-bold">Remote View — {id}</h1>
      <div className="max-w-sm">
        <DeviceStream deviceId={id} width={720} height={1280} />
      </div>
    </div>
  );
}
