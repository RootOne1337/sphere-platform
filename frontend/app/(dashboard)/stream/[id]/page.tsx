'use client';

import { use } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { ArrowLeft, Monitor, Navigation } from 'lucide-react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { Button } from '@/components/ui/button';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { TeachingWorkbench } from '@/src/features/stream/TeachingWorkbench';

interface Props { params: Promise<{ id: string }>; }

export default function DeviceStreamPage({ params }: Props) {
  const { id } = use(params);
  const access = useCapabilities();
  const query = useSearchParams();
  const teaching = query.get('teach') === '1';
  const destination = teaching && query.get('world') === '1';

  return (
    <PageFrame className="max-w-[1800px]">
      {destination ? <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3"><div className="rounded-xl border border-primary/30 bg-primary/10 p-2.5 text-primary"><Navigation size={20}/></div>
        <div><h1 className="text-2xl font-semibold tracking-tight">Навигация</h1><p className="text-sm text-muted-foreground">Поездка к метке по живому экрану</p></div></div>
        <Button variant="outline" size="sm" asChild><Link href={`/stream/${encodeURIComponent(id)}?teach=1`}>Студия маршрутов</Link></Button>
      </header> : <PageHeading
        eyebrow="Просмотр устройства"
        title={teaching ? 'Запись маршрута' : 'Видеопоток'}
        description={teaching ? `Устройство ${id}` : `Устройство ${id} · экран и диагностические счётчики браузера и Android-агента.`}
        actions={<div className="flex flex-wrap gap-2"><Button asChild><Link href={`/stream/${encodeURIComponent(id)}?teach=1&world=1`}>Навигация по карте</Link></Button><Button asChild variant="outline"><Link href={`/stream/${encodeURIComponent(id)}${teaching ? '' : '?teach=1'}`}>{teaching ? 'Обычный поток' : 'Записать маршрут'}</Link></Button><Button asChild variant="outline"><Link href={`/devices/${encodeURIComponent(id)}`}><ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />Карточка устройства</Link></Button></div>}
      />}
      {teaching ? <TeachingWorkbench key={id+String(destination)} deviceId={id} destination={destination} readOnly={!access.can('stream:control')} /> : <section aria-label={`Видеопоток устройства ${id}`} className="overflow-hidden rounded-2xl border border-border bg-card p-2 shadow-soft sm:p-3">
        <div className="mb-3 flex items-center gap-2 px-1 text-xs text-muted-foreground"><Monitor className="h-3.5 w-3.5" aria-hidden="true" /><span className="font-mono">{id}</span><span className="ml-auto">Поток подключается отдельно от статуса heartbeat</span></div>
        <div className="mx-auto w-full max-w-[1100px] overflow-hidden rounded-xl border border-border bg-black">
          <DeviceStream deviceId={id} enableDiagnostics enableScreenshot enableNavigation enableStaticInput readOnly={!access.can('stream:control')} />
        </div>
      </section>}
    </PageFrame>
  );
}
