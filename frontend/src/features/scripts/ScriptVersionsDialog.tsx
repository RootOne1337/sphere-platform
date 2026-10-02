'use client';

import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import type { ScriptDetail, ScriptVersion } from '@/lib/hooks/useScripts';
import { redactScriptDag } from './scriptPresentation';
import { changedDagPaths, parseDetail, parseVersion, scriptWriteFailure, verifyRollback } from './versionWorkflow';

type Confirmation = { kind: 'archive' | 'rollback'; baseline: ScriptDetail; target: ScriptVersion | null };
const time = (value: string) => new Date(value).toLocaleString('ru-RU', { timeZone: 'UTC' }) + ' UTC';
export function ScriptVersionsDialog({ scriptId, orgId, scope, canManage, available, onClose }: {
  scriptId: string; orgId: string; scope: string; canManage: boolean; available: boolean; onClose: () => void;
}) {
  const qc = useQueryClient();
  const [chosen, setChosen] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [pending, setPending] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const live = useRef(true);
  const busy = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const detail = useQuery({ queryKey: ['script-workflow', scope, scriptId], queryFn: async ({ signal }) => {
    const { data } = await api.get('/scripts/' + scriptId, { params: { include_dag: false }, signal });
    return parseDetail(data, scriptId, orgId);
  }, staleTime: 0, refetchInterval: 15_000, refetchIntervalInBackground: false });
  const versionId = chosen ?? detail.data?.current_version_id ?? '';
  function versionQuery(id: string) {
    return { queryKey: ['script-version', scope, scriptId, id], queryFn: async ({ signal }: { signal: AbortSignal }) => {
      const { data } = await api.get(`/scripts/${scriptId}/versions/${id}`, { signal });
      const version = parseVersion(data, scriptId, id);
      if (!version.dag || !version.dag_hash) throw new Error('Missing version contents');
      return version;
    }, enabled: Boolean(id), staleTime: Infinity };
  }
  const selected = useQuery(versionQuery(versionId));
  const current = useQuery(versionQuery(detail.data?.current_version_id ?? ''));
  const valid = available && Boolean(detail.data?.current_version_id) && !detail.isError && !detail.isFetching && !uncertain;
  const active = valid && !detail.data?.is_archived && canManage && !pending;
  const selectedValid = Boolean(selected.data && detail.data?.versions.some(v => v.id === selected.data.id && v.dag_hash === selected.data.dag_hash))
    && !selected.isError && !selected.isFetching;
  const rollbackReady = active && selectedValid && versionId !== detail.data?.current_version_id;
  const capturedCurrent = confirmation?.baseline.current_version_id;
  const confirmationValid = active && capturedCurrent === detail.data?.current_version_id
    && (confirmation?.kind === 'archive' || (rollbackReady && confirmation?.target?.id === versionId));
  const diff = selected.data && current.data ? changedDagPaths(current.data.dag, selected.data.dag) : null;

  async function refresh() {
    setConfirmation(null);
    const result = await detail.refetch();
    if (live.current && !result.isError) { setUncertain(false); setError(null); }
  }
  function prepare(kind: Confirmation['kind']) {
    if (!active || !detail.data || (kind === 'rollback' && !rollbackReady)) return;
    setError(null); setNotice(null);
    setConfirmation({ kind, baseline: detail.data, target: kind === 'rollback' ? selected.data! : null });
  }
  async function submit() {
    if (busy.current || !confirmation || !confirmationValid) return;
    const captured = confirmation;
    busy.current = true; setPending(true); setError(null); setNotice(null);
    try {
      if (captured.kind === 'archive') {
        const response = await api.delete('/scripts/' + scriptId, { params: { expected_current_version_id: captured.baseline.current_version_id } });
        if (response.status !== 204) throw new Error('Unconfirmed archive');
        if (live.current) {
          const read = await detail.refetch();
          if (read.isError || !read.data?.is_archived) throw new Error('Archive readback failed');
          if (live.current) setNotice('Архивирование подтверждено свежим чтением API. Сценарий и все версии доступны в архиве.');
        }
      } else {
        const response = await api.post(`/scripts/${scriptId}/versions/${captured.target!.id}/rollback`,
          { expected_current_version_id: captured.baseline.current_version_id });
        if (response.status !== 200) throw new Error('Unconfirmed rollback');
        const result = verifyRollback(response.data, scriptId, orgId, captured.target!, captured.baseline);
        if (live.current) {
          setChosen(result.id);
          setNotice(`Создана версия v${result.version} с DAG выбранной версии. Уже созданные задания сохраняют прежнюю версию.`);
          await detail.refetch();
        }
      }
      if (live.current) { setConfirmation(null); void qc.invalidateQueries({ queryKey: ['scripts'] }); }
    } catch (failure) {
      if (live.current) { const state = scriptWriteFailure(failure); setError(state.message); setUncertain(state.uncertain); setConfirmation(null); }
    } finally {
      busy.current = false;
      if (live.current) setPending(false);
    }
  }
  return <Dialog open onOpenChange={open => { if (!open && !busy.current) onClose(); }}>
    <DialogContent className="sm:max-w-[1080px]" onEscapeKeyDown={event => { if (busy.current) event.preventDefault(); }} onPointerDownOutside={event => { if (busy.current) event.preventDefault(); }}>
      <DialogHeader><DialogTitle>История и управление сценарием</DialogTitle><DialogDescription>Неизменяемые версии, сравнение DAG, контролируемый откат и архив. Просмотр не запускает задания Android.</DialogDescription></DialogHeader>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0"><p className="break-words font-semibold">{detail.data?.name ?? 'Сценарий'}</p><p className="mt-1 text-xs text-muted-foreground">{detail.data?.is_archived ? 'Архив · история сохранена' : 'Активный сценарий'} · текущая версия v{(detail.data?.current_version as ScriptVersion | undefined)?.version ?? '—'}</p></div>
        <Button variant="outline" disabled={pending || detail.isFetching} onClick={() => { void refresh(); }}>Обновить состояние</Button>
      </div>
      {notice && <p role="status" className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm">{notice}</p>}
      {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
      {!available && <p role="alert" className="text-sm text-destructive">Каталог недоступен. Запись заблокирована до обновления.</p>}
      {detail.isError ? <p role="alert" className="text-sm text-destructive">Не удалось прочитать сценарий или проверить принадлежность организации. Обновите состояние.</p> : detail.isPending ? <p role="status">Читаем историю…</p> : <>
        <label className="space-y-2 text-sm">Версия для просмотра
          <select aria-label="Версия для просмотра" value={versionId} disabled={pending} onChange={event => { setChosen(event.target.value); setConfirmation(null); setNotice(null); }} className="block h-10 w-full rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            {[...detail.data.versions].sort((a,b) => b.version - a.version).map(version => <option key={version.id} value={version.id}>v{version.version}{version.id === detail.data.current_version_id ? ' · текущая' : ''} · {time(version.created_at)}</option>)}
          </select>
        </label>
        {selected.isError ? <div role="alert" className="flex flex-wrap items-center justify-between gap-3 text-sm"><span>Не удалось прочитать выбранную версию. Откат заблокирован.</span><Button variant="outline" onClick={() => { void selected.refetch(); }}>Повторить чтение версии</Button></div> : selected.isPending ? <p role="status">Читаем выбранный DAG…</p> : selected.data && <>
          <dl className="grid min-w-0 gap-3 rounded-lg border bg-muted/30 p-3 text-xs sm:grid-cols-2">
            <div className="min-w-0 sm:col-span-2"><dt className="text-muted-foreground">SHA-256 выбранной версии</dt><dd className="mt-1 break-all font-mono">{selected.data.dag_hash}</dd></div>
            <div><dt className="text-muted-foreground">Создана</dt><dd className="mt-1">{time(selected.data.created_at)}</dd></div>
            <div className="min-w-0"><dt className="text-muted-foreground">Автор версии</dt><dd className="mt-1 break-all font-mono">{selected.data.created_by_id ?? 'Не сообщён'}</dd></div>
          </dl>
          {selected.data.notes && <p className="break-words text-sm text-muted-foreground">Описание: {selected.data.notes}</p>}
          <div className="grid min-w-0 gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <pre aria-label="DAG выбранной версии" className="max-h-96 min-w-0 overflow-auto overscroll-contain rounded-lg border bg-muted/20 p-4 text-xs leading-5"><code>{JSON.stringify(redactScriptDag(selected.data.dag), null, 2)}</code></pre>
            <section aria-label="Сравнение с текущей версией" className="min-w-0 rounded-lg border p-3 text-sm"><p className="font-medium">Сравнение с текущей версией</p>
              {current.isError ? <p role="alert" className="mt-2 text-destructive">Текущий DAG недоступен.<Button variant="outline" size="sm" onClick={() => { void current.refetch(); }}>Повторить сравнение</Button></p> : diff ? <><p className="mt-2">Изменено полей: {diff.paths.length}{diff.truncated ? '+' : ''}</p><p className="mt-2 text-xs text-muted-foreground">Сравнивается структура после скрытия полей учётных данных. Совпадение показанного DAG не подтверждает равенство скрытых значений; полный хеш возвращает сервер.</p><ul className="mt-3 max-h-48 space-y-1 overflow-auto font-mono text-xs">{diff.paths.map(path => <li className="break-all" key={path}>{path}</li>)}</ul></> : <p role="status" className="mt-2">Читаем текущий DAG…</p>}
            </section>
          </div>
        </>}
        {!canManage && <p className="text-sm text-muted-foreground">Ваша роль разрешает только просмотр этого сценария.</p>}
        {confirmation && <section aria-label="Подтверждение изменения сценария" className="space-y-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm">
          <p className="font-medium">{confirmation.kind === 'archive' ? 'Архивирование сценария' : `Откат с текущей версии к v${confirmation.target?.version}`}</p>
          <p>{confirmation.kind === 'archive' ? 'Архивирование скроет сценарий из активного каталога и запретит новые изменения и запуск. Оно не отменяет уже созданные задания; версии и история сохраняются.' : 'Откат создаст новую неизменяемую версию с DAG выбранной версии и сделает её текущей. Исходные версии сохраняются. Уже созданные задания продолжают работать с прежней версией; следующие запуски используют новую текущую.'}</p>
          {capturedCurrent !== detail.data.current_version_id && <p role="alert">Текущая версия изменилась. Обновите состояние и подтвердите действие заново.</p>}
          <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={pending} onClick={() => setConfirmation(null)}>Отмена действия</Button><Button disabled={!confirmationValid} onClick={() => { void submit(); }}>{pending ? 'Сохраняем…' : confirmation.kind === 'archive' ? 'Подтвердить архивирование' : 'Подтвердить откат'}</Button></div>
        </section>}
        <div className="flex flex-wrap justify-end gap-2"><Button variant="outline" disabled={!active} onClick={() => prepare('archive')}>В архив</Button><Button disabled={!rollbackReady} onClick={() => prepare('rollback')}>Откатить к выбранной версии</Button><Button variant="outline" disabled={pending} onClick={onClose}>Закрыть окно</Button></div>
      </>}
    </DialogContent>
  </Dialog>;
}
