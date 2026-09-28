'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowRight, Braces, Play, Plus, RefreshCw, Workflow } from 'lucide-react';
import { useScripts } from '@/lib/hooks/useScripts';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { RunScriptModal } from '@/components/sphere/RunScriptModal';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';

export default function ScriptsPage() {
  const { data: scriptsData, isLoading, isError, refetch } = useScripts();
  const scripts = scriptsData?.items ?? [];
  const [runTarget, setRunTarget] = useState<{ id: string; name: string } | null>(null);

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Автоматизация Android"
        title="Сценарии"
        description="Создавайте визуальные сценарии, проверяйте их структуру и запускайте на выбранных устройствах."
        actions={<Button asChild><Link href="/scripts/builder"><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Новый сценарий</Link></Button>}
      />

      {isError ? (
        <Card><CardContent className="flex flex-col gap-3 p-6 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-medium">Не удалось загрузить сценарии</p><p className="mt-1 text-sm text-muted-foreground">Проверьте доступ к API и повторите запрос.</p></div><Button type="button" variant="outline" onClick={() => { void refetch(); }}><RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />Повторить</Button></CardContent></Card>
      ) : isLoading ? (
        <div className="space-y-3" aria-label="Загрузка сценариев" aria-busy="true">{Array.from({ length: 4 }, (_, index) => <div key={index} className="h-24 animate-pulse rounded-xl border border-border bg-card motion-reduce:animate-none" />)}</div>
      ) : scripts.length === 0 ? (
        <Card><CardContent className="flex min-h-64 flex-col items-center justify-center p-8 text-center"><span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary"><Workflow className="h-6 w-6" aria-hidden="true" /></span><p className="mt-4 font-semibold">Сценариев пока нет</p><p className="mt-1 max-w-md text-sm text-muted-foreground">Создайте первый сценарий и добавьте шаги в редакторе.</p><Button asChild className="mt-5"><Link href="/scripts/builder"><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Создать сценарий</Link></Button></CardContent></Card>
      ) : (
        <section aria-label="Список сценариев" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"><span>Показано {scripts.length}{scriptsData?.total != null && scriptsData.total !== scripts.length ? ` из ${scriptsData.total}` : ''}</span><span>Структура сценария хранится в версиях backend</span></div>
          {scripts.map((script) => (
            <Card key={script.id} className="group shadow-soft transition-[border-color,box-shadow] duration-200 hover:border-primary/30 hover:shadow-md motion-reduce:transition-none">
              <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary"><Braces className="h-5 w-5" aria-hidden="true" /></span>
                  <div className="min-w-0">
                    <h2 className="truncate font-semibold tracking-tight">{script.name}</h2>
                    <p className="mt-1 line-clamp-2 text-sm leading-5 text-muted-foreground">{script.description || 'Описание не добавлено'}</p>
                    <p className="mt-2 text-xs text-muted-foreground">Обновлён {new Date(script.updated_at).toLocaleString('ru-RU')}</p>
                  </div>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
                  <Badge variant="outline" className="rounded-full px-3">{script.node_count} {script.node_count % 10 === 1 && script.node_count % 100 !== 11 ? 'шаг' : script.node_count % 10 >= 2 && script.node_count % 10 <= 4 && (script.node_count % 100 < 12 || script.node_count % 100 > 14) ? 'шага' : 'шагов'}</Badge>
                  {script.is_archived && <Badge variant="secondary" className="rounded-full">В архиве</Badge>}
                  <Button type="button" size="sm" onClick={() => setRunTarget({ id: script.id, name: script.name })} disabled={script.is_archived}><Play className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />Запустить</Button>
                  <Button asChild size="sm" variant="outline"><Link href={`/scripts/builder?id=${encodeURIComponent(script.id)}`}>Открыть <ArrowRight className="ml-1.5 h-3.5 w-3.5" aria-hidden="true" /></Link></Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </section>
      )}

      {runTarget && <RunScriptModal scriptId={runTarget.id} scriptName={runTarget.name} open onClose={() => setRunTarget(null)} />}
    </PageFrame>
  );
}
