import { AlertCircle, BookOpen, ShieldCheck } from 'lucide-react';
import { actionContract, actionParameterErrors, fieldRule } from '@/lib/dag/actionParameters';
import type { DagNode } from '@/lib/dag/export';

const effects = { flow: 'Переходы и ожидание', read: 'Чтение состояния', control: 'Управление Android',
  destructive: 'Удаление данных или остановка', code: 'Исполнение кода', context: 'Контекст задания', network: 'Сеть Android' };

/** Requirements are actual JSON rules, never synthetic capability or execution ACKs. */
export function ActionContractCard({ action }: { action: DagNode['action'] }) {
  const spec = Object.hasOwn(actionContract.actions, action.type) ? actionContract.actions[action.type] : undefined;
  const errors = actionParameterErrors([{ action }]);
  if (!spec) return null;
  const check = typeof action.check === 'string' ? action.check : '';
  const parameterRule = spec.checks && Object.hasOwn(spec.checks, check) ? fieldRule(spec.checks[check]) : undefined;
  const fields = { ...spec.fields, ...(parameterRule?.fields ? Object.fromEntries(Object.entries(parameterRule.fields).map(([name, rule]) => [`params.${name}`, rule])) : {}) };
  const required = Object.entries(fields).filter(([, rule]) => fieldRule(rule).required).map(([name]) => name);
  return <section aria-label="Контракт действия" className="space-y-2.5 rounded-xl border bg-muted/25 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]"><span className="flex items-center gap-1.5 font-semibold"><BookOpen className="size-3.5 text-primary" />Контракт параметров {actionContract.version}</span><span className={`rounded-md border px-1.5 py-0.5 ${spec.effect === 'destructive' ? 'border-destructive/30 text-destructive' : 'text-muted-foreground'}`}>{effects[spec.effect]}</span></div>
    <p className="text-[11px] leading-5 text-muted-foreground">{spec.note}</p>
    {!!required.length && <p className="break-words text-[11px] leading-5">Обязательные поля: <span className="font-mono">{required.join(', ')}</span></p>}
    {errors.length ? <div role="status" className="space-y-1 rounded-lg bg-amber-500/10 p-2 text-[11px] text-amber-800 dark:text-amber-300"><p className="flex items-center gap-1.5 font-medium"><AlertCircle className="size-3.5 shrink-0" />Исправьте перед проверкой и публикацией</p>{errors.slice(0, 8).map((error, index) => <p key={index} className="break-words"><code>{error.loc.slice(2).join('.')}</code>: {error.msg}</p>)}{errors.length > 8 && <p>Ещё {errors.length - 8} ошибок</p>}</div>
      : <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><ShieldCheck className="size-3.5 shrink-0" />Параметры проверены локально. Возможности APK не проверены.</p>}
    {!!Object.keys(fields).length && <details className="text-[11px]"><summary className="cursor-pointer font-medium">Типы и ограничения полей</summary><dl className="mt-2 space-y-1.5">{Object.entries(fields).map(([name, raw]) => { const rule = fieldRule(raw); return <div key={name} className="flex flex-wrap justify-between gap-x-3 gap-y-1 border-t pt-1.5"><dt className="break-all font-mono">{name}{rule.required ? ' *' : ''}</dt><dd className="min-w-0 break-words text-muted-foreground">{rule.type}{rule.min !== undefined || rule.max !== undefined ? ` · ${rule.min ?? 0}–${rule.max ?? '∞'}` : ''}{rule.enum ? ` · ${rule.enum.join(' / ')}` : ''}{rule.nonblank ? ' · непустое' : ''}</dd></div>; })}</dl><p className="mt-2 leading-5 text-muted-foreground">Для строк предел измеряется в символах, для массива — в элементах, для объекта — в ключах. Значения не преобразуются и не подставляются автоматически.</p></details>}
  </section>;
}
