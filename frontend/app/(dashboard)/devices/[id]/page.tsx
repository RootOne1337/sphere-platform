'use client';

import { use } from 'react';
import Link from 'next/link';
import { ArrowLeft, Monitor } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';
import { DeviceInspectorDetail } from '@/src/features/devices/DeviceInspectorDetail';

export default function DeviceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <PageFrame>
    <PageHeading eyebrow="Каталог Sphere" title="Карточка устройства" description="Телеметрия, история исполнения и диагностика выбранного Android-устройства." actions={<><Button asChild variant="outline"><Link href={`/stream/${encodeURIComponent(id)}`}><Monitor className="mr-2 h-4 w-4" aria-hidden />Открыть поток</Link></Button><Button asChild variant="ghost"><Link href="/devices"><ArrowLeft className="mr-2 h-4 w-4" aria-hidden />Реестр</Link></Button></>} />
    <section className="rounded-2xl border border-border bg-card p-4 shadow-soft sm:p-6"><DeviceInspectorDetail key={id} deviceId={id} fullPage /></section>
  </PageFrame>;
}
