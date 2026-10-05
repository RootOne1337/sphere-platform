'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Archive, ArrowRight, Braces, Clock3, Code2, FileCode2, GitBranch, History, LayoutGrid, List, Play, Plus, RefreshCw, Search, Settings2, ShieldCheck, Workflow } from 'lucide-react';
import { useScript, useScripts, type Script, type ScriptVersion } from '@/lib/hooks/useScripts';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { RunScriptModal } from '@/components/sphere/RunScriptModal';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';
import { CatalogPagination } from '@/src/shared/ui/catalog-pagination';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { formatScriptStepCount, getCurrentScriptVersion, getScriptStepCount, redactScriptDag } from '@/src/features/scripts/scriptPresentation';
import { ScriptVersionsDialog } from '@/src/features/scripts/ScriptVersionsDialog';
import { canWriteScript } from '@/src/features/scripts/versionWorkflow';
import { useAuthStore } from '@/lib/store';

type CatalogPreferences = {
  view: 'list' | 'cards'; density: 'comfortable' | 'compact'; perPage: 25 | 50 | 100;
  description: boolean; identifiers: boolean; hash: boolean; created: boolean;
};
const DEFAULT_PREFERENCES: CatalogPreferences = {
  view: 'list', density: 'comfortable', perPage: 50, description: true,
  identifiers: false, hash: true, created: false,
};
function readPreferences(key: string): CatalogPreferences {
  try {
    const raw = localStorage.getItem(key);
    if (!raw || raw.length > 4096) return { ...DEFAULT_PREFERENCES };
    const value = JSON.parse(raw);
    if (!value || typeof value !== 'object' || value.schema !== 1) return { ...DEFAULT_PREFERENCES };
    return {
      view: value.view === 'cards' ? 'cards' : 'list',
      density: value.density === 'compact' ? 'compact' : 'comfortable',
      perPage: value.perPage === 25 || value.perPage === 100 ? value.perPage : 50,
      description: typeof value.description === 'boolean' ? value.description : true,
      identifiers: typeof value.identifiers === 'boolean' ? value.identifiers : false,
      hash: typeof value.hash === 'boolean' ? value.hash : true,
      created: typeof value.created === 'boolean' ? value.created : false,
    };
  } catch { return { ...DEFAULT_PREFERENCES }; }
}
const dateTime = (value: string) => Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('ru-RU') : 'Не сообщается';

export default function ScriptsPage() {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [state, setState] = useState<'active' | 'archived' | 'all'>('active');
  const actor = useAuthStore(value => value.user);
  const session = useAuthStore(value => value.sessionVersion);
  const scope = `${actor?.org_id}:${actor?.id}:${actor?.role}:${session}`;
  const preferenceKey = actor?.org_id && actor.id ? `sphere:scripts:catalog:v1:${encodeURIComponent(actor.org_id)}:${encodeURIComponent(actor.id)}` : null;
  const [storedPreferences, setStoredPreferences] = useState<{ key: string | null; value: CatalogPreferences }>({ key: null, value: { ...DEFAULT_PREFERENCES } });
  const preferences = storedPreferences.key === preferenceKey ? storedPreferences.value : DEFAULT_PREFERENCES;
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [storageNotice, setStorageNotice] = useState<string | null>(null);
  useEffect(() => {
    setStoredPreferences({ key: preferenceKey, value: preferenceKey ? readPreferences(preferenceKey) : { ...DEFAULT_PREFERENCES } });
    setStorageNotice(null);
  }, [preferenceKey]);
  function updatePreferences(update: Partial<CatalogPreferences>) {
    const next = { ...preferences, ...update };
    setStoredPreferences({ key: preferenceKey, value: next });
    if (update.perPage != null && update.perPage !== preferences.perPage) { setPage(1); setInspectedScriptId(null); }
    if (!preferenceKey) return;
    try { localStorage.setItem(preferenceKey, JSON.stringify({ schema: 1, ...next })); setStorageNotice(null); }
    catch { setStorageNotice('Браузер не разрешил сохранить настройки. До закрытия страницы они остаются в памяти.'); }
  }
  const [workflow, setWorkflow] = useState<{ id: string; scope: string } | null>(null);
  const query = useDebounce(search.trim(), 300);
  const searching = search.trim() !== query;
  const { data: scriptsData, isLoading, isError, isFetching, refetch } = useScripts({ query: query || undefined, page, per_page: preferences.perPage, ...(state === 'active' ? {} : { state }) });
  const scripts = scriptsData?.items ?? [];
  const [runTarget, setRunTarget] = useState<{ id: string; name: string; version: ScriptVersion | null; scope: string } | null>(null);
  const [inspectedScriptId, setInspectedScriptId] = useState<{ id: string; scope: string } | null>(null);
  const publishedOnPage = scripts.filter(script => getCurrentScriptVersion(script) != null).length;

  return (
    <PageFrame className="gap-5">
      <PageHeading
        eyebrow="Автоматизация / библиотека"
        title="Сценарии"
        description="Версии, исходный код и запуск Android-автоматизации — в одном рабочем пространстве."
        actions={<><Button variant="outline" onClick={() => setSettingsOpen(true)}><Settings2 className="mr-2 h-4 w-4" aria-hidden="true" />Настроить каталог</Button><Button asChild><Link href="/scripts/builder"><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Новый сценарий</Link></Button></>}
      />

      <section aria-label="Сводка каталога" className="grid grid-cols-2 gap-3">
        <div className="flex min-w-0 items-center gap-3 rounded-xl border bg-card p-3 sm:p-4"><span className="hidden rounded-lg bg-primary/10 p-2.5 text-primary sm:block"><Workflow className="h-5 w-5" aria-hidden="true" /></span><div className="min-w-0"><p className="text-xs text-muted-foreground">В выбранном каталоге · API</p><p className="mt-1 text-xl font-semibold tabular-nums">{isError || searching || isLoading ? '—' : scriptsData?.total ?? '—'} <span className="text-xs font-normal text-muted-foreground">сценариев</span></p></div></div>
        <div className="flex min-w-0 items-center gap-3 rounded-xl border bg-card p-3 sm:p-4"><span className="hidden rounded-lg bg-muted p-2.5 text-muted-foreground sm:block"><GitBranch className="h-5 w-5" aria-hidden="true" /></span><div className="min-w-0"><p className="text-xs text-muted-foreground">Опубликовано · эта страница</p><p className="mt-1 text-xl font-semibold tabular-nums">{isError || searching || isLoading ? '—' : publishedOnPage} <span className="text-xs font-normal text-muted-foreground">из {isError || searching || isLoading ? '—' : scripts.length}</span></p></div></div>
      </section>

      <div className="space-y-3 rounded-xl border bg-card p-3 sm:p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Состояние каталога сценариев" className="flex max-w-full flex-wrap gap-1 rounded-lg bg-muted/50 p-1">
          {(['active', 'archived', 'all'] as const).map(value => <Button key={value} size="sm" variant={state === value ? 'secondary' : 'ghost'} aria-pressed={state === value} onClick={() => { setState(value); setPage(1); setInspectedScriptId(null); }}>{value === 'active' ? 'Активные' : value === 'archived' ? 'Архив' : 'Все сценарии'}</Button>)}
        </div>
        <div role="group" aria-label="Вид каталога" className="flex gap-1 rounded-lg border p-1">
          <Button size="sm" variant={preferences.view === 'list' ? 'secondary' : 'ghost'} aria-label="Подробный список" aria-pressed={preferences.view === 'list'} onClick={() => updatePreferences({ view: 'list' })}><List className="mr-1.5 h-4 w-4" aria-hidden="true" />Список</Button>
          <Button size="sm" variant={preferences.view === 'cards' ? 'secondary' : 'ghost'} aria-label="Карточки сценариев" aria-pressed={preferences.view === 'cards'} onClick={() => updatePreferences({ view: 'cards' })}><LayoutGrid className="mr-1.5 h-4 w-4" aria-hidden="true" />Карточки</Button>
        </div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" aria-hidden="true" /><Input aria-label="Поиск сценариев во всём каталоге" placeholder="Поиск по имени сценария…" className="w-full pl-9" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); setInspectedScriptId(null); }} /></div>
          <Button variant="outline" disabled={isFetching || searching} onClick={() => { void refetch(); }}><RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />Обновить сценарии</Button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-muted-foreground"><span>Поиск на сервере по всему каталогу</span><span>{preferences.perPage} на странице · {preferences.density === 'compact' ? 'компактный' : 'обычный'} вид</span></div>
        <p className="flex items-start gap-1.5 border-t border-border/50 pt-2 text-xs leading-5 text-muted-foreground"><ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />Запуск закрепляется за опубликованной версией. Устройства выбираются перед отправкой задания.</p>
      </div>
      {storageNotice && <p role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs">{storageNotice}</p>}

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
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"><span>Показано {scripts.length}{scriptsData?.total != null && scriptsData.total !== scripts.length ? ` из ${scriptsData.total}` : ''}</span><span>Версии и хеши из API · даты в часовом поясе браузера</span></div>
          <div className={preferences.view === 'cards' ? 'grid items-start gap-3 xl:grid-cols-2 2xl:grid-cols-3' : 'space-y-3'}>
          {scripts.map((script) => (
            <Card key={script.id} className="min-w-0 overflow-hidden shadow-none transition-colors duration-150 hover:border-primary/30 motion-reduce:transition-none">
              <CardContent className={preferences.density === 'compact' ? 'space-y-3 p-3 sm:p-4' : 'space-y-4 p-4 sm:p-5'}>
                <div className={preferences.view === 'list' ? 'grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)]' : 'space-y-4'}>
                <div className="flex min-w-0 items-start gap-3">
                  <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border bg-muted/40 text-primary"><FileCode2 className="h-4 w-4" aria-hidden="true" /></span>
                  <div className="min-w-0">
                    <h2 className="break-words font-semibold leading-6 tracking-tight [overflow-wrap:anywhere]">{script.name}</h2>
                    {preferences.description && <p className={`${preferences.density === 'compact' ? 'line-clamp-1' : 'line-clamp-2'} mt-1 break-words text-sm leading-5 text-muted-foreground`}>{script.description || 'Описание не добавлено'}</p>}
                    {preferences.identifiers && <p className="mt-2 break-all font-mono text-[11px] text-muted-foreground">ID: {script.id}</p>}
                  </div>
                </div>
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2"><Badge variant={script.is_archived ? 'secondary' : 'outline'} className={`rounded-md ${script.is_archived ? '' : 'border-primary/20 bg-primary/5 text-primary'}`}>{script.is_archived ? <Archive className="mr-1 h-3 w-3" aria-hidden="true" /> : <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />}{script.is_archived ? 'В архиве' : 'Активен'}</Badge><Badge variant="outline" className="rounded-md" title={getScriptStepCount(script) == null ? 'API не сообщило количество шагов' : undefined}>{formatScriptStepCount(getScriptStepCount(script))}</Badge><span className="text-xs font-medium">{getCurrentScriptVersion(script) ? `v${getCurrentScriptVersion(script)!.version}` : typeof script.current_version === 'number' ? `v${script.current_version}` : 'Версия не сообщается'}</span></div>
                  {preferences.hash && <p className="break-all font-mono text-[11px] leading-5 text-muted-foreground" title={getCurrentScriptVersion(script)?.dag_hash ?? undefined}>SHA-256: {getCurrentScriptVersion(script)?.dag_hash ? `${getCurrentScriptVersion(script)!.dag_hash!.slice(0, 18)}…` : 'Не сообщается'}</p>}
                  {preferences.identifiers && getCurrentScriptVersion(script) && <p className="break-all font-mono text-[11px] text-muted-foreground">Версия ID: {getCurrentScriptVersion(script)!.id}</p>}
                </div>
                <div className="min-w-0 text-xs leading-5"><p className="flex items-center gap-1.5 text-muted-foreground"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />Обновлён</p><p className="mt-0.5 tabular-nums">{dateTime(script.updated_at)}</p>{preferences.created && <p className="mt-1 text-muted-foreground">Создан {dateTime(script.created_at)}</p>}</div>
                </div>
                <div className="flex flex-wrap items-center gap-2 border-t border-border/60 pt-3">
                  {!script.is_archived && <Button asChild size="sm" variant="outline"><Link href={`/scripts/builder?id=${encodeURIComponent(script.id)}`}>Открыть <ArrowRight className="ml-1.5 h-3.5 w-3.5" aria-hidden="true" /></Link></Button>}
                  <Button type="button" size="sm" onClick={() => setRunTarget({ id: script.id, name: script.name, version: getCurrentScriptVersion(script), scope })} disabled={script.is_archived || !getCurrentScriptVersion(script) || !actor} title={!getCurrentScriptVersion(script) ? 'Для запуска требуется опубликованная версия из API' : undefined}><Play className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />Запустить</Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-expanded={inspectedScriptId?.id === script.id && inspectedScriptId.scope === scope}
                    onClick={() => setInspectedScriptId((current) => current?.id === script.id && current.scope === scope ? null : { id: script.id, scope })}
                  >
                    <Code2 className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                    {inspectedScriptId?.id === script.id && inspectedScriptId.scope === scope ? 'Скрыть DAG' : 'Посмотреть DAG'}
                  </Button>
                  <Button type="button" size="sm" variant="ghost" className="whitespace-normal text-left" disabled={!actor} onClick={() => setWorkflow({ id: script.id, scope })}><History className="mr-1.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />История и управление</Button>
                </div>
              </CardContent>
              {inspectedScriptId?.id === script.id && inspectedScriptId.scope === scope && <ScriptDagInspector key={`${scope}:${script.id}`} script={script} onClose={() => setInspectedScriptId(null)} />}
            </Card>
          ))}
          </div>
        </section>
      )}

      {!isError && !isLoading && !searching && scriptsData && <CatalogPagination page={page} perPage={preferences.perPage} total={scriptsData.total} busy={isFetching} label="сценарии" onPageChange={(next) => { setPage(next); setInspectedScriptId(null); }} />}

      {runTarget?.scope === scope && <RunScriptModal key={`${scope}:${runTarget.id}`} scriptId={runTarget.id} scriptName={runTarget.name} expectedVersion={runTarget.version ?? undefined} requireVersion initialTargetMode="select" open onClose={() => setRunTarget(null)} />}
      {workflow?.scope === scope && actor && <ScriptVersionsDialog key={`${scope}:${workflow.id}`} scriptId={workflow.id} orgId={actor.org_id} scope={scope} canManage={canWriteScript(actor.role)} available={!isError && !searching} onClose={() => setWorkflow(null)} />}
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}><DialogContent className="sm:max-w-lg"><DialogHeader><DialogTitle>Настройки каталога сценариев</DialogTitle><DialogDescription>Компоновка и детализация списка. Настройки сохраняются в этом браузере отдельно для пользователя и организации.</DialogDescription></DialogHeader><div className="space-y-5">
        <fieldset className="space-y-2"><legend className="text-sm font-medium">Плотность</legend><div className="grid grid-cols-2 gap-2">{(['comfortable', 'compact'] as const).map(value => <Button key={value} variant={preferences.density === value ? 'secondary' : 'outline'} aria-pressed={preferences.density === value} onClick={() => updatePreferences({ density: value })}>{value === 'comfortable' ? 'Обычная' : 'Компактная'}</Button>)}</div></fieldset>
        <label className="block space-y-2 text-sm font-medium">Сценариев на странице<select aria-label="Сценариев на странице" className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm" value={preferences.perPage} onChange={event => updatePreferences({ perPage: Number(event.target.value) as CatalogPreferences['perPage'] })}>{[25, 50, 100].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
        <fieldset className="space-y-2"><legend className="mb-2 text-sm font-medium">Детали сценария</legend>{([{ key: 'description', label: 'Описание сценария' }, { key: 'hash', label: 'Хеш опубликованной версии' }, { key: 'identifiers', label: 'Идентификаторы сценария и версии' }, { key: 'created', label: 'Дата создания' }] as const).map(field => <label key={field.key} className="flex cursor-pointer items-start gap-3 rounded-lg border bg-muted/20 p-3 text-sm"><input type="checkbox" className="mt-0.5 h-4 w-4 accent-primary" checked={preferences[field.key]} onChange={event => updatePreferences({ [field.key]: event.target.checked })} /><span>{field.label}</span></label>)}</fieldset>
        {!preferenceKey && <p role="status" className="text-xs text-muted-foreground">Для сохранения настроек после перезагрузки требуется подтверждённая учётная запись.</p>}
        <div className="flex flex-wrap justify-between gap-2 border-t pt-4"><Button variant="ghost" onClick={() => updatePreferences({ ...DEFAULT_PREFERENCES })}>Сбросить настройки</Button><Button onClick={() => setSettingsOpen(false)}>Готово</Button></div>
      </div></DialogContent></Dialog>
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
