'use client';

import { useEffect, useId, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/src/shared/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { useScriptCatalog, type ScriptCatalogItem } from '@/lib/hooks/useScriptCatalog';
import { useApplicationProfiles, type ApplicationProfile } from './applicationProfiles';
import { useRevisionedApplicationResource } from './useRevisionedApplicationResource';

const REGISTRATION_LIMITS = [
  ['max_concurrent_registrations', 'Параллельные регистрации', 1, 100],
  ['registration_timeout_seconds', 'Тайм-аут регистрации, с', 60, 7200],
] as const;
const FARMING_LIMITS = [
  ['max_concurrent_farming', 'Параллельные фарм-сессии', 1, 500],
  ['farming_session_duration_seconds', 'Длительность фарм-сессии, с', 300, 86400],
  ['default_target_level', 'Целевой уровень', 1, 100],
  ['cooldown_between_sessions_minutes', 'Пауза между сессиями, мин', 0, 1440],
] as const;
const LIMITS = [...REGISTRATION_LIMITS, ...FARMING_LIMITS];
type Limit = (typeof LIMITS)[number];
type Policy = Record<Limit[0], number> & {
  registration_enabled: boolean;
  registration_script_id: string | null;
  farming_enabled: boolean;
  farming_script_id: string | null;
};
type PolicyReceipt = Policy & { application_profile_id: string; revision: number };
type PolicyChanges = Partial<Policy>;
type AutomationMode = 'registration' | 'farming';
const SELECT = 'mt-1 h-10 w-full rounded-md border border-input bg-background px-2 text-sm disabled:opacity-60';

function validLimits(policy: Partial<Policy>): boolean {
  return LIMITS.every(([key, , min, max]) => {
    const value = policy[key];
    return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
  });
}

function validatePolicy(value: unknown, profileId: string): PolicyReceipt {
  const data = value as Partial<PolicyReceipt> | null;
  if (!data || data.application_profile_id !== profileId || typeof data.revision !== 'number'
    || !Number.isSafeInteger(data.revision) || data.revision < 0 || !validLimits(data)
    || !(['registration', 'farming'] as const).every(mode => {
      const script = data[`${mode}_script_id`];
      return typeof data[`${mode}_enabled`] === 'boolean' && (script === null || typeof script === 'string' && Boolean(script));
    })) throw new Error('Некорректные параметры автоматизации.');
  return data as PolicyReceipt;
}

function matchesPolicy(observed: PolicyReceipt, requested: PolicyChanges) {
  return (Object.keys(requested) as (keyof Policy)[]).every(key => observed[key] === requested[key]);
}

export function ProfileAutomationSettings() {
  const access = useCapabilities();
  const [open, setOpen] = useState(false);
  if (!access.can('pipeline:read')) return null;
  return <>
    <Button variant="outline" size="sm" onClick={() => setOpen(true)}>Автоматизация по приложениям</Button>
    {open && <ProfileAutomationDialog onClose={() => setOpen(false)} />}
  </>;
}

function ProfileAutomationDialog({ onClose }: { onClose: () => void }) {
  const access = useCapabilities();
  const canReadCatalog = access.can('account:read');
  const catalog = useApplicationProfiles(canReadCatalog);
  const profiles = canReadCatalog ? catalog.data?.filter(profile => profile.source === 'tenant') ?? [] : [];
  const [profileId, setProfileId] = useState('');
  const [phase, setPhase] = useState<'idle' | 'dirty' | 'pending'>('idle');
  const profile = profiles.find(item => item.id === profileId);
  return <Dialog open onOpenChange={next => { if (!next && phase === 'idle') onClose(); }}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>Автоматизация по приложениям</DialogTitle>
        <DialogDescription>Настройки регистрации и фарма для устройств с сохранённой привязкой к выбранному профилю.</DialogDescription>
      </DialogHeader>
      {!canReadCatalog && <p role="status" className="text-sm">Для выбора профиля требуется право account:read.</p>}
      {catalog.isLoading && <p role="status">Загружаем каталог приложений…</p>}
      {catalog.isError && <div role="alert" className="space-y-2"><p>Каталог приложений недоступен.</p><Button variant="outline" onClick={() => { void catalog.refetch(); }}>Перечитать каталог</Button></div>}
      {catalog.data && canReadCatalog && <label className="block text-sm">Профиль приложения
        <select className={SELECT} value={profileId} disabled={!catalog.isSuccess || phase !== 'idle'} onChange={event => setProfileId(event.target.value)}>
          <option value="">Выберите профиль</option>
          {profiles.map(item => <option key={item.id} value={item.id}>{item.name} · {item.key}</option>)}
        </select>
      </label>}
      {catalog.isSuccess && canReadCatalog && profiles.length === 0 && <p className="text-sm">Создайте профиль в разделе «Игровые аккаунты → Приложения и серверы».</p>}
      {profile && <PolicyEditor key={profile.id} profile={profile} catalogConfirmed={catalog.isSuccess} setPhase={setPhase} />}
      <Button variant="outline" className="justify-self-end" disabled={phase === 'pending'} onClick={onClose}>{phase === 'dirty' ? 'Закрыть без сохранения' : 'Готово'}</Button>
    </DialogContent>
  </Dialog>;
}

function PolicyEditor({ profile, catalogConfirmed, setPhase }: { profile: ApplicationProfile; catalogConfirmed: boolean; setPhase: (phase: 'idle' | 'dirty' | 'pending') => void }) {
  const access = useCapabilities();
  const canWrite = access.can('pipeline:write');
  const canReadScripts = access.can('script:read');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const searchTerm = useDebounce(search.trim());
  const scripts = useScriptCatalog({ query: searchTerm || undefined, page, per_page: 50, state: 'active' }, canReadScripts);
  const [chosenScripts, setChosenScripts] = useState<ScriptCatalogItem[]>([]);
  const options = canReadScripts && !scripts.isError ? scripts.data?.items.filter(script => Boolean(script.current_version_id)) ?? [] : [];
  const pageCount = Math.max(1, Math.ceil((scripts.data?.total ?? 0) / 50));
  const resource = useRevisionedApplicationResource(`/application-profiles/${encodeURIComponent(profile.id)}/automation-policy`,
    value => validatePolicy(value, profile.id), matchesPolicy);
  const [changes, setChanges] = useState<PolicyChanges>({});
  const [baseRevision, setBaseRevision] = useState<number | null>(null);
  const [saved, setSaved] = useState(false);
  const current = resource.query.data;
  const form = current && { ...current, ...changes };
  const dirty = Object.keys(changes).length > 0;
  const staleDraft = dirty && current?.revision !== baseRevision;
  const writable = canWrite && catalogConfirmed && resource.query.isSuccess && !resource.query.isFetching && !resource.pending && !resource.blocked && !staleDraft;
  const readyProfile = Boolean(profile.android_package && profile.servers.length);
  const validForm = form && validLimits(form) && (!form.registration_enabled || form.registration_script_id)
    && (!form.farming_enabled || form.farming_script_id);
  const canSave = writable && dirty && Boolean(validForm);

  useEffect(() => { setPhase(resource.pending ? 'pending' : dirty ? 'dirty' : 'idle'); }, [dirty, resource.pending, setPhase]);
  useEffect(() => () => setPhase('idle'), [setPhase]);

  function edit(patch: PolicyChanges) {
    if (!writable || !current) return;
    const chosen = options.find(option => option.id === patch.registration_script_id || option.id === patch.farming_script_id);
    if (chosen) {
      setChosenScripts(previous => [chosen, ...previous.filter(option => option.id !== chosen.id)].slice(0, 2));
    }
    if (!dirty) setBaseRevision(current.revision);
    setSaved(false);
    setChanges(previous => {
      const next = { ...previous, ...patch };
      for (const key of Object.keys(next) as (keyof Policy)[]) {
        if (next[key] === current[key]) delete next[key];
      }
      return next;
    });
  }

  async function save() {
    if (!canSave || !current) return;
    if (await resource.save(changes, current.revision)) {
      setChanges({});
      setSaved(true);
    }
  }

  async function reload() {
    if (await resource.reload()) { setChanges({}); setSaved(false); }
  }

  return <div className="space-y-4">
    {!canWrite && <p role="status" className="text-sm">Для изменения требуется право pipeline:write.</p>}
    {resource.query.isLoading && <p role="status">Читаем сохранённые настройки…</p>}
    {resource.query.isError && <p role="alert">Настройки профиля недоступны.</p>}
    {current && <p className="text-sm text-muted-foreground">Сохранённая версия {current.revision}. Регистрация {current.registration_enabled ? 'включена' : 'выключена'}, фарм {current.farming_enabled ? 'включён' : 'выключен'}.</p>}
    <p className="text-sm text-muted-foreground">Запуск требует Android-пакет, привязанный сервер и активный сценарий с опубликованной версией. При запуске сервер выбирает текущую опубликованную версию сценария.</p>
    {!readyProfile && <p className="text-sm">Укажите Android-пакет и сервер в разделе <Link className="underline" href="/accounts">«Игровые аккаунты»</Link>, чтобы включить режимы.</p>}
    {form && <>
      {canReadScripts && <div className="space-y-2">
        <label className="block text-sm">Найти сценарий
          <input className={SELECT} type="search" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} />
        </label>
        {scripts.isError && <div role="alert" className="text-sm">Список сценариев недоступен. <Button size="sm" variant="outline" onClick={() => { void scripts.refetch(); }}>Перечитать сценарии</Button></div>}
        {scripts.isFetching && <p role="status" className="text-sm">Загружаем сценарии…</p>}
        {(pageCount > 1 || page > 1) && <div className="flex flex-wrap items-center gap-2 text-sm">
          <Button size="sm" variant="outline" disabled={page <= 1 || scripts.isFetching} onClick={() => setPage(page - 1)}>Предыдущая страница сценариев</Button>
          <span>Страница {page}{scripts.data && ` из ${pageCount}`}</span>
          <Button size="sm" variant="outline" disabled={page >= pageCount || scripts.isFetching} onClick={() => setPage(page + 1)}>Следующая страница сценариев</Button>
        </div>}
      </div>}
      <AutomationFields mode="registration" title="Регистрация" limits={REGISTRATION_LIMITS} form={form} options={options}
        chosenScripts={canReadScripts ? chosenScripts : []} writable={writable} readyProfile={readyProfile} canReadScripts={canReadScripts} edit={edit} />
      <AutomationFields mode="farming" title="Фарм" limits={FARMING_LIMITS} form={form} options={options}
        chosenScripts={canReadScripts ? chosenScripts : []} writable={writable} readyProfile={readyProfile} canReadScripts={canReadScripts} edit={edit} />
      {dirty && !validForm && <p role="status" className="text-sm">Проверьте диапазоны чисел и сценарий для каждого включённого режима.</p>}
    </>}
    {staleDraft && <p role="alert">Настройки изменились на сервере. Перечитайте сохранённые значения перед новой записью.</p>}
    {resource.error && <p role="alert" className="text-sm text-destructive">{resource.error}</p>}
    {saved && <p role="status">Настройки профиля подтверждены повторным чтением.</p>}
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" disabled={resource.pending || resource.query.isFetching} onClick={() => { void reload(); }}>{dirty ? 'Перечитать и сбросить правки' : 'Перечитать настройки профиля'}</Button>
      <Button disabled={!canSave} onClick={() => { void save(); }}>{resource.pending ? 'Проверяем сохранение…' : 'Сохранить настройки профиля'}</Button>
    </div>
  </div>;
}

function AutomationFields({ mode, title, limits, form, options, chosenScripts, writable, readyProfile, canReadScripts, edit }: {
  mode: AutomationMode; title: string; limits: readonly Limit[]; form: Policy; options: ScriptCatalogItem[]; chosenScripts: ScriptCatalogItem[];
  writable: boolean; readyProfile: boolean; canReadScripts: boolean; edit: (patch: PolicyChanges) => void;
}) {
  const script = form[`${mode}_script_id`];
  const selectedName = chosenScripts.find(option => option.id === script)?.name;
  const enabled = form[`${mode}_enabled`];
  const limitHelp = useId();
  return <fieldset disabled={!writable} className="min-w-0 space-y-3 rounded-lg border p-3">
    <legend className="px-2 text-sm font-medium">{title}</legend>
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={enabled} disabled={!enabled && (!readyProfile || !script)} onChange={event => edit({ [`${mode}_enabled`]: event.target.checked })} />
      {mode === 'registration' ? 'Включить регистрацию' : 'Включить фарм'}
    </label>
    <label className="block text-sm">{mode === 'registration' ? 'Сценарий регистрации' : 'Сценарий фарма'}
      <select className={SELECT} disabled={!canReadScripts} value={script ?? ''} onChange={event => {
        const value = event.target.value;
        edit(value ? { [`${mode}_script_id`]: value } : { [`${mode}_script_id`]: null, [`${mode}_enabled`]: false });
      }}>
        <option value="">Без сценария</option>
        {script && !options.some(option => option.id === script) && <option value={script}>{selectedName ?? `ID сценария · ${script}`}</option>}
        {options.map(option => <option key={option.id} value={option.id}>{option.name} · {option.id.slice(0, 8)}</option>)}
      </select>
    </label>
    <div className="grid gap-2 sm:grid-cols-2">{limits.map(([key, label, min, max]) => <div key={key} className="text-sm">
      <label className="block" htmlFor={`${limitHelp}-input-${key}`}>{label}</label>
      <input id={`${limitHelp}-input-${key}`} className={SELECT} type="number" min={min} max={max} step={1} value={Number.isNaN(form[key]) ? '' : form[key]}
        aria-describedby={`${limitHelp}-${key}`} onChange={event => edit({ [key]: event.target.valueAsNumber })} />
      <span className="text-xs text-muted-foreground" id={`${limitHelp}-${key}`}>{min}–{max}</span>
    </div>)}</div>
  </fieldset>;
}
