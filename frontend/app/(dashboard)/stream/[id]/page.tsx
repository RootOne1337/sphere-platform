'use client';

import { use } from 'react';
import Link from 'next/link';
import { ArrowLeft, Monitor } from 'lucide-react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { Button } from '@/components/ui/button';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';

interface Props { params: Promise<{ id: string }>; }

export default function DeviceStreamPage({ params }: Props) {
  const { id } = use(params);

  return (
    <PageFrame className="max-w-[1800px]">
      <PageHeading
        eyebrow="Просмотр устройства"
        title="Видеопоток"
        description={`Устройство ${id} · экран и диагностические счётчики браузера и Android-агента.`}
        actions={<Button asChild variant="outline"><Link href={`/devices/${encodeURIComponent(id)}`}><ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />Карточка устройства</Link></Button>}
      />
      <section aria-label={`Видеопоток устройства ${id}`} className="overflow-hidden rounded-2xl border border-border bg-card p-2 shadow-soft sm:p-3">
        <div className="mb-3 flex items-center gap-2 px-1 text-xs text-muted-foreground"><Monitor className="h-3.5 w-3.5" aria-hidden="true" /><span className="font-mono">{id}</span><span className="ml-auto">Поток подключается отдельно от статуса heartbeat</span></div>
        <div className="mx-auto w-full max-w-[1100px] overflow-hidden rounded-xl border border-border bg-black">
          <DeviceStream deviceId={id} enableDiagnostics enableScreenshot />
        </div>
      </section>
    </PageFrame>
  );
}
