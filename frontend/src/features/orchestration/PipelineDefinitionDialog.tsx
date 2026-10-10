'use client';

import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { definitionDraft, definitionFailure, parsePipelineDefinition, presentDefinition, validateDefinitionDraft, verifyDefinitionReceipt,
  type DefinitionDraft, type DefinitionPatch, type PipelineDefinition } from './pipelineDefinition';

type Edit = { baseline: PipelineDefinition; draft: DefinitionDraft };
type Confirmation = { baseline: PipelineDefinition; patch: DefinitionPatch; kind: 'edit' } | { baseline: PipelineDefinition; patch: { is_active: boolean }; kind: 'activation' };
const time = (value: string) => new Date(value).toLocaleString('ru-RU', { timeZone: 'UTC' }) + ' UTC';

export function PipelineDefinitionDialog({ pipelineId, orgId, scope, canManage, initialAction, onClose }: {
  pipelineId: string; orgId: string; scope: string; canManage: boolean; initialAction: 'view' | 'activation'; onClose: () => void;
}) {
  const qc = useQueryClient();
  const [edit, setEdit] = useState<Edit | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [pending, setPending] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [discard, setDiscard] = useState<'close' | 'reload' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const busy = useRef(false);
  const live = useRef(true);
  const initialized = useRef(false);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  const detail = useQuery({ queryKey: ['pipeline-definition', scope, pipelineId], queryFn: async ({ signal }) => {
    const { data } = await api.get('/pipelines/' + pipelineId, { signal });
    return parsePipelineDefinition(data, pipelineId, orgId);
  }, retry: false, staleTime: 0, refetchInterval: 15000, refetchIntervalInBackground: false });
  const fresh = Boolean(detail.data) && !detail.isError && !detail.isFetching;
  const writable = fresh && canManage && !pending && !uncertain && !blocked;
  const changedUnderDraft = Boolean(edit && detail.data?.updated_at !== edit.baseline.updated_at);
  const confirmationValid = writable && confirmation?.baseline.updated_at === detail.data?.updated_at;
  useEffect(() => {
    if (initialized.current || !fresh || !detail.data) return;
    initialized.current = true;
    if (initialAction === 'activation' && canManage) setConfirmation({ kind: 'activation', baseline: detail.data, patch: { is_active: !detail.data.is_active } });
  }, [fresh, detail.data, initialAction, canManage]);
  function prepareActivation() {
    if (!writable || !detail.data || edit) return;
    setError(null); setNotice(null);
    setConfirmation({ kind: 'activation', baseline: detail.data, patch: { is_active: !detail.data.is_active } });
  }
  async function refresh() {
    if (busy.current) return;
    setConfirmation(null);
    const read = await detail.refetch();
    if (live.current && !read.isError) { setUncertain(false); setBlocked(false); setError(null); }
  }
  function prepareEdit() {
    if (!writable || !edit || changedUnderDraft) return;
    try {
      const patch = validateDefinitionDraft(edit.draft, edit.baseline);
      if (!Object.keys(patch).length) { setNotice('Нет изменений для сохранения.'); return; }
      setError(null); setNotice(null); setConfirmation({ kind: 'edit', baseline: edit.baseline, patch });
    } catch (failure) { setError((failure as Error).message); }
  }
  async function submit() {
    if (busy.current || !confirmation || !confirmationValid) return;
    const captured = confirmation;
    busy.current = true; setPending(true); setError(null); setNotice(null);
    try {
      const response = captured.kind === 'edit'
        ? await api.patch('/pipelines/' + pipelineId, { ...captured.patch, expected_updated_at: captured.baseline.updated_at })
        : await api.post(`/pipelines/${pipelineId}/toggle`, null, { params: { active: captured.patch.is_active, expected_updated_at: captured.baseline.updated_at } });
      if (response.status !== 200) throw new Error('Unconfirmed write');
      const result = verifyDefinitionReceipt(response.data, captured.baseline, captured.patch);
      if (!live.current) return;
      qc.setQueryData(['pipeline-definition', scope, pipelineId], result);
      setEdit(null); setConfirmation(null);
      setNotice(`Сохранение подтверждено API: версия v${result.version}, ${time(result.updated_at)}. Действующие запуски не отменены.`);
      void qc.invalidateQueries({ queryKey: ['pipelines'] });
    } catch (failure) {
      if (live.current) { const state = definitionFailure(failure); setError(state.message); setUncertain(state.uncertain); setBlocked(true); setConfirmation(null); }
    } finally { busy.current = false; if (live.current) setPending(false); }
  }
  function requestClose() { if (!busy.current) { if (edit) setDiscard('close'); else onClose(); } }
  const data = detail.data;
  return <Dialog open onOpenChange={open => { if (!open) requestClose(); }}>
    <DialogContent className="sm:max-w-[1100px]" onEscapeKeyDown={event => { if (busy.current || edit) event.preventDefault(); if (edit && !busy.current) setDiscard('close'); }} onPointerDownOutside={event => { if (busy.current || edit) event.preventDefault(); }}>
      <DialogHeader><DialogTitle>Определение и управление pipeline</DialogTitle><DialogDescription>Состояние из API, параметры и переходы шагов. Изменение требует проверки и подтверждения; просмотр не запускает устройства.</DialogDescription></DialogHeader>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0"><h2 className="break-words text-lg font-semibold">{data?.name ?? 'Загрузка определения…'}</h2><p className="mt-1 break-all font-mono text-xs text-muted-foreground">ID: {pipelineId}</p></div>
        <Button variant="outline" disabled={pending || detail.isFetching} onClick={() => { void refresh(); }}>Перечитать состояние</Button>
      </div>
      {detail.isError && <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm text-destructive">Не удалось получить достоверное определение pipeline. Изменение недоступно; предыдущий снимок не считается текущим.</p>}
      {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">{error}</p>}
      {notice && <p role="status" className="rounded-lg border border-success/30 bg-success/5 p-3 text-sm">{notice}</p>}
      {data && !detail.isError && <>
        <dl className="grid min-w-0 grid-cols-2 gap-3 rounded-lg border bg-muted/30 p-4 text-sm md:grid-cols-4">
          <div><dt className="text-muted-foreground">Допуск новых запусков</dt><dd className="mt-1 font-semibold">{data.is_active ? 'Включён' : 'Выключен'}</dd></div>
          <div><dt className="text-muted-foreground">Определение</dt><dd className="mt-1">v{data.version} · {data.steps.length} шагов</dd></div>
          <div><dt className="text-muted-foreground">Глобальный таймаут</dt><dd className="mt-1">{data.global_timeout_ms} мс</dd></div>
          <div><dt className="text-muted-foreground">Обновлено</dt><dd className="mt-1 text-xs">{time(data.updated_at)}</dd></div>
          <div className="col-span-2 min-w-0"><dt className="text-muted-foreground">Организация / автор</dt><dd className="mt-1 break-all font-mono text-xs">{data.org_id} / {data.created_by_id ?? 'не указан'}</dd></div>
          <div className="col-span-2"><dt className="text-muted-foreground">Создано</dt><dd className="mt-1 text-xs">{time(data.created_at)}</dd></div>
        </dl>
        <p className="rounded-lg border bg-muted/20 p-3 text-xs text-muted-foreground">Выключение закрывает новые запуски и не останавливает действующие. Шаги, входная схема и таймаут изменяются только при отсутствии queued/running/waiting/paused запусков. Входная схема хранится как описание; исполнитель сейчас не валидирует по ней входные параметры. Общие повторы ({data.max_retries}) сохранены в шаблоне; исполнитель использует повторы отдельных шагов.</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={!writable || Boolean(edit)} onClick={() => { if (data) { setEdit({ baseline: data, draft: definitionDraft(data) }); setConfirmation(null); setError(null); setNotice(null); } }}>Редактировать определение</Button>
          <Button variant="outline" disabled={!writable || Boolean(edit)} onClick={prepareActivation}>{data.is_active ? 'Выключить новые запуски' : 'Включить новые запуски'}</Button>
          {!canManage && <span className="self-center text-xs text-muted-foreground">Ваша роль разрешает только просмотр.</span>}
        </div>
        {edit ? <section className="space-y-4 rounded-lg border p-4" aria-label="Черновик определения">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">Черновик · версия v{edit.baseline.version}</h3><Button variant="outline" disabled={pending} onClick={() => setDiscard('reload')}>Отбросить черновик</Button></div>
          {changedUnderDraft && <p role="alert" className="text-sm text-warning">Серверное определение изменилось. Черновик сохранён, но запись блокируется; отбросьте черновик и заново прочитайте актуальную версию.</p>}
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-2 text-sm">Название<Input disabled={pending} value={edit.draft.name} onChange={e => setEdit({ ...edit, draft: { ...edit.draft, name: e.target.value } })} /></label>
            <label className="space-y-2 text-sm">Глобальный таймаут, мс<Input type="number" min={10000} max={259200000} disabled={pending} value={edit.draft.global_timeout_ms} onChange={e => setEdit({ ...edit, draft: { ...edit.draft, global_timeout_ms: e.target.value } })} /></label>
            {(['description', 'tags', 'input_schema', 'steps'] as const).map(field => <label key={field} className={`min-w-0 space-y-2 text-sm ${field === 'steps' ? 'md:col-span-2' : ''}`}>
              {{ description: 'Описание (пустое — очистить)', tags: 'Теги JSON', input_schema: 'Входная схема JSON', steps: 'Шаги JSON' }[field]}
              <textarea className="block w-full resize-y rounded-md border bg-background p-3 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" rows={field === 'steps' ? 14 : 4} disabled={pending} value={edit.draft[field]} onChange={e => setEdit({ ...edit, draft: { ...edit.draft, [field]: e.target.value } })} />
            </label>)}
          </div>
          <p className="text-xs text-muted-foreground">Редактор содержит исходные параметры. Секреты скрыты в обзоре и подтверждении; не вставляйте их в снимки экрана. Проверка графа не заменяет проверку семантики параметров каждого обработчика.</p>
          <Button disabled={!writable || changedUnderDraft} onClick={prepareEdit}>Проверить изменения</Button>
        </section> : <div className="grid min-w-0 gap-4 lg:grid-cols-[2fr_1fr]">
          <section className="min-w-0 space-y-3"><h3 className="font-semibold">Шаги и переходы</h3>{data.steps.map((step, i) => <details key={i} className="rounded-lg border p-3">
            <summary className="cursor-pointer break-words text-sm">{i + 1}. {String(step.name ?? step.id ?? 'Шаг')} · {String(step.type ?? 'тип неизвестен')}</summary>
            <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded bg-muted/40 p-3 text-xs">{presentDefinition(step)}</pre>
          </details>)}</section>
          <section className="min-w-0 space-y-3"><h3 className="font-semibold">Описание и входные данные</h3><p className="whitespace-pre-wrap break-words text-sm">{data.description ?? 'Описание не задано'}</p><p className="break-words text-xs">Теги: {data.tags.join(', ') || '—'}</p><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-lg border bg-muted/20 p-3 text-xs">{presentDefinition(data.input_schema)}</pre></section>
        </div>}
      </>}
      {confirmation && <section className="space-y-3 rounded-lg border border-warning/40 bg-warning/5 p-4" aria-label="Подтверждение изменения">
        <h3 className="font-semibold">Проверка перед записью</h3><p className="break-all text-xs">{confirmation.baseline.id} · v{confirmation.baseline.version} · {confirmation.baseline.updated_at}</p>
        <p className="text-sm">{confirmation.kind === 'activation' ? confirmation.patch.is_active ? 'Разрешить новые запуски этого pipeline?' : 'Запретить новые запуски этого pipeline? Действующие задания продолжатся.' : 'Сохранить перечисленные изменения определения? Конфликт отклонит всю запись.'}</p>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-lg border bg-background p-3 text-xs">{presentDefinition(confirmation.patch)}</pre>
        {!confirmationValid && <p role="alert" className="text-sm text-warning">Состояние изменилось или ещё проверяется. Перечитайте данные и подтвердите заново.</p>}
        <div className="flex flex-wrap gap-2"><Button disabled={!confirmationValid} onClick={() => { void submit(); }}>{pending ? 'Сохраняем…' : 'Подтвердить запись'}</Button><Button variant="outline" disabled={pending} onClick={() => setConfirmation(null)}>Отменить подтверждение</Button></div>
      </section>}
      {discard && <section className="space-y-3 rounded-lg border border-warning/40 p-4"><p>Отбросить несохранённый черновик?</p><div className="flex gap-2"><Button disabled={pending} onClick={() => { const action = discard; setDiscard(null); setEdit(null); setConfirmation(null); if (action === 'close') onClose(); else void refresh(); }}>Да, отбросить</Button><Button variant="outline" onClick={() => setDiscard(null)}>Сохранить черновик</Button></div></section>}
    </DialogContent>
  </Dialog>;
}
