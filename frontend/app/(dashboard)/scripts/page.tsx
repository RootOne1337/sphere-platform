'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowRight, Braces, Code2, Play, Plus, RefreshCw, Workflow } from 'lucide-react';
import { useScript, useScripts, type Script, type ScriptVersion } from '@/lib/hooks/useScripts';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { RunScriptModal } from '@/components/sphere/RunScriptModal';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';
import { CatalogPagination } from '@/src/shared/ui/catalog-pagination';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { formatScriptStepCount, getCurrentScriptVersion, getScriptStepCount, redactScriptDag } from '@/src/features/scripts/scriptPresentation';
import { ScriptVersionsDialog } from '@/src/features/scripts/ScriptVersionsDialog';
import { canWriteScript } from '@/src/features/scripts/versionWorkflow';
import { useAuthStore } from '@/lib/store';

export default function ScriptsPage() {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [state, setState] = useState<'active' | 'archived' | 'all'>('active');
  const actor = useAuthStore(value => value.user);
  const session = useAuthStore(value => value.sessionVersion);
  const scope = `${actor?.org_id}:${actor?.id}:${actor?.role}:${session}`;
  const [workflow, setWorkflow] = useState<{ id: string; scope: string } | null>(null);
  const query = useDebounce(search.trim(), 300);
  const searching = search.trim() !== query;
  const { data: scriptsData, isLoading, isError, isFetching, refetch } = useScripts({ query: query || undefined, page, per_page: 50, ...(state === 'active' ? {} : { state }) });
  const scripts = scriptsData?.items ?? [];
  const [runTarget, setRunTarget] = useState<{ id: string; name: string; version: ScriptVersion | null; scope: string } | null>(null);
  const [inspectedScriptId, setInspectedScriptId] = useState<string | null>(null);

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Автоматизация Android"
        title="Сценарии"
        description="Создавайте визуальные сценарии, проверяйте их структуру и запускайте на выбранных устройствах."
        actions={<Button asChild><Link href="/scripts/builder"><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Новый сценарий</Link></Button>}
      />

      <div className="flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Состояние каталога сценариев" className="flex flex-wrap gap-1 rounded-lg border p-1">
          {(['active', 'archived', 'all'] as const).map(value => <Button key={value} size="sm" variant={state === value ? 'secondary' : 'ghost'} aria-pressed={state === value} onClick={() => { setState(value); setPage(1); setInspectedScriptId(null); }}>{value === 'active' ? 'Активные' : value === 'archived' ? 'Архив' : 'Все сценарии'}</Button>)}
        </div>
        <Input aria-label="Поиск сценариев во всём каталоге" placeholder="Найти сценарий по имени…" className="sm:max-w-md" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); setInspectedScriptId(null); }} />
        <Button variant="outline" disabled={isFetching || searching} onClick={() => { void refetch(); }}>Обновить сценарии</Button>
        <span className="text-xs text-muted-foreground">Поиск выполняется на сервере по всему каталогу</span>
      </div>

      {searching ? (
        <p role="status" className="text-sm text-muted-foreground">Обновляем поиск…</p>
      ) : isError ? (
        <Card><CardContent className="flex flex-col gap-3 p-6 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-medium">Не удалось загрузить сценарии</p><p className="mt-1 text-sm text-muted-foreground">Проверьте доступ к API и повторите запрос.</p></div><Button type="button" variant="outline" onClick={() => { void refetch(); }}><RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />Повторить</Button></CardContent></Card>
      ) : isLoading ? (
        <div className="space-y-3" aria-label="Загрузка сценариев" aria-busy="true">{Array.from({ length: 4 }, (_, index) => <div key={index} className="h-24 animate-pulse rounded-xl border border-border bg-card motion-reduce:animate-none" />)}</div>
      ) : scripts.length === 0 ? (
        <Card><CardContent className="flex min-h-64 flex-col items-center justify-center p-8 text-center"><span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary"><Workflow className="h-6 w-6" aria-hidden="true" /></span><p className="mt-4 font-semibold">{query ? 'По вашему запросу сценарии не найдены' : page > 1 ? 'На этой странице сценариев нет' : 'Сценариев пока нет'}</p><p className="mt-1 max-w-md text-sm text-muted-foreground">{query ? 'Измените запрос: поиск охватывает весь каталог.' : page > 1 ? 'Вернитесь на предыдущую страницу или обновите каталог.' : 'Создайте первый сценарий и добавьте шаги в редакторе.'}</p><Button asChild className="mt-5"><Link href="/scripts/builder"><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Создать сценарий</Link></Button></CardContent></Card>
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
                  <Badge variant="outline" className="rounded-full px-3" title={getScriptStepCount(script) == null ? 'API не сообщило количество шагов' : undefined}>{formatScriptStepCount(getScriptStepCount(script))}</Badge>
                  {script.is_archived && <Badge variant="secondary" className="rounded-full">В архиве</Badge>}
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-expanded={inspectedScriptId === script.id}
                    onClick={() => setInspectedScriptId((current) => current === script.id ? null : script.id)}
                  >
                    <Code2 className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                    {inspectedScriptId === script.id ? 'Скрыть DAG' : 'Посмотреть DAG'}
                  </Button>
                  <Button type="button" size="sm" onClick={() => setRunTarget({ id: script.id, name: script.name, version: getCurrentScriptVersion(script), scope })} disabled={script.is_archived}><Play className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />Запустить</Button>
                  <Button type="button" size="sm" variant="outline" disabled={!actor} onClick={() => setWorkflow({ id: script.id, scope })}>История и управление</Button>
                  {!script.is_archived && <Button asChild size="sm" variant="outline"><Link href={`/scripts/builder?id=${encodeURIComponent(script.id)}`}>Открыть <ArrowRight className="ml-1.5 h-3.5 w-3.5" aria-hidden="true" /></Link></Button>}
                </div>
              </CardContent>
              {inspectedScriptId === script.id && <ScriptDagInspector script={script} onClose={() => setInspectedScriptId(null)} />}
            </Card>
          ))}
        </section>
      )}

      {!isError && !isLoading && !searching && scriptsData && <CatalogPagination page={page} perPage={50} total={scriptsData.total} busy={isFetching} label="сценарии" onPageChange={(next) => { setPage(next); setInspectedScriptId(null); }} />}

      {runTarget?.scope === scope && <RunScriptModal key={`${scope}:${runTarget.id}`} scriptId={runTarget.id} scriptName={runTarget.name} expectedVersion={runTarget.version ?? undefined} requireVersion open onClose={() => setRunTarget(null)} />}
      {workflow?.scope === scope && actor && <ScriptVersionsDialog key={`${scope}:${workflow.id}`} scriptId={workflow.id} orgId={actor.org_id} scope={scope} canManage={canWriteScript(actor.role)} available={!isError && !searching} onClose={() => setWorkflow(null)} />}
    </PageFrame>
  );
}

function ScriptDagInspector({ script, onClose }: { script: Script; onClose: () => void }) {
  const { data, isLoading, isError, refetch, isFetching } = useScript(script.id, { includeDag: true });
  const currentVersion = data ? getCurrentScriptVersion(data) : getCurrentScriptVersion(script);
  const legacyVersion = typeof data?.current_version === 'number' ? data.current_version : null;
  const dag = currentVersion?.dag ?? data?.dag ?? null;
  const displayedDag = dag == null ? null : JSON.stringify(redactScriptDag(dag), null, 2);

  return (
    <section aria-label={`Исходник сценария ${script.name}`} className="border-t border-border/70 bg-muted/20 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="flex items-center gap-2 text-sm font-semibold"><Braces className="h-4 w-4 text-primary" aria-hidden="true" />DAG сценария · только чтение</p>
          <p className="mt-1 text-xs text-muted-foreground">Версия и хеш взяты из ответа API. Открытие панели не запускает и не меняет сценарий.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button type="button" size="sm" variant="outline" onClick={() => { void refetch(); }} disabled={isFetching}>
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />Обновить DAG
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onClose}>Свернуть</Button>
        </div>
      </div>

      {isLoading ? (
        <p role="status" className="mt-4 rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">Загружаем версию сценария…</p>
      ) : isError ? (
        <div role="alert" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
          <span>Не удалось прочитать сценарий из API.</span>
          <Button type="button" size="sm" variant="outline" onClick={() => { void refetch(); }}>Повторить</Button>
        </div>
      ) : (
        <>
          <dl className="mt-4 grid gap-3 rounded-lg border border-border/70 bg-background/70 p-3 text-xs sm:grid-cols-3">
            <div><dt className="text-muted-foreground">Текущая версия</dt><dd className="mt-1 font-medium">{currentVersion?.version ?? legacyVersion ?? 'Не сообщается'}</dd></div>
            <div className="min-w-0 sm:col-span-2"><dt className="text-muted-foreground">SHA-256 DAG</dt><dd className="mt-1 break-all font-mono">{currentVersion?.dag_hash ?? 'API не вернул хеш'}</dd></div>
          </dl>
          {currentVersion?.notes && <p className="mt-3 text-xs text-muted-foreground">Описание версии: {currentVersion.notes}</p>}
          {displayedDag ? (
            <pre className="mt-3 max-h-[32rem] overflow-auto rounded-lg border border-border bg-background p-4 text-xs leading-5 text-foreground"><code>{displayedDag}</code></pre>
          ) : (
            <p className="mt-3 rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">В текущем ответе API нет DAG для этой версии.</p>
          )}
          {data?.versions?.length ? (
            <details className="mt-3 rounded-lg border border-border/70 bg-background/60 p-3">
              <summary className="cursor-pointer text-xs font-medium">История версий · {data.versions.length}</summary>
              <ol className="mt-3 space-y-2">
                {[...data.versions].sort((a, b) => b.version - a.version).map((version) => (
                  <li key={version.id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t border-border/60 pt-2 text-xs">
                    <span className="font-medium">v{version.version}{version.notes ? ` · ${version.notes}` : ''}</span>
                    <span className="break-all font-mono text-muted-foreground">{version.dag_hash ?? 'Хеш не сообщается'}</span>
                  </li>
                ))}
              </ol>
            </details>
          ) : null}
        </>
      )}
    </section>
  );
}
