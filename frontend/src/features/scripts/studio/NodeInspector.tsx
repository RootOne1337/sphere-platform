'use client';
import { useState } from 'react';
import { Settings2, GitBranch, SlidersHorizontal } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/components/ui/input';
import { FIELD_LABELS } from './presentation';
import { defaultAction } from '@/lib/dag/studio';
import { ACTION_TYPES, type DagNode } from '@/lib/dag/export';
import { ActionContractCard } from './ActionContractCard';
import { actionContract, fieldRule } from '@/lib/dag/actionParameters';

const choices: Record<string, string[]> = { strategy: ['xpath', 'id', 'text', 'desc', 'class'], direction: ['up', 'down', 'left', 'right'],
  method: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD'] };
const checkParams: Record<string, Record<string, unknown>> = {
  battery_above: { level: 20 }, element_exists: { selector: '', strategy: 'xpath', timeout_ms: 5000 },
  element_gone: { selector: '', strategy: 'xpath', timeout_ms: 5000 }, text_equals: { selector: '', strategy: 'xpath', value: '' },
  text_contains: { selector: '', strategy: 'xpath', text: '' }, variable_equals: { key: '', value: '' },
  variable_contains: { key: '', value: '' }, http_status: { node_id: '', value: 200 },
};
function parametersFor(type: string, check: string) {
  return type === 'assert' && check === 'text_contains' ? { selector: '', strategy: 'xpath', value: '' } : checkParams[check];
}
export function NodeInspector({ source, onChange, nodes, writable, pending, apply, cancel }: {
  source: string; onChange: (source: string) => void; nodes: { id: string }[]; writable: boolean; pending: boolean; apply: () => void; cancel: () => void;
}) {
  const [tab, setTab] = useState<'fields' | 'json'>('fields');
  const [extraField, setExtraField] = useState('');
  let node: DagNode | null = null;
  try { const parsed = JSON.parse(source); if (parsed?.action && typeof parsed.action === 'object') node = parsed; } catch { /* Source errors stay editable. */ }
  function update(path: string[], value: unknown) {
    if (!node) return;
    const next = structuredClone(node);
    let record = next as unknown as Record<string, unknown>;
    for (const key of path.slice(0, -1)) {
      if (!record[key] || typeof record[key] !== 'object' || Array.isArray(record[key])) record[key] = {};
      record = record[key] as Record<string, unknown>;
    }
    record[path.at(-1)!] = value;
    if (path.join('.') === 'action.check') next.action.params = structuredClone(parametersFor(next.action.type, String(value)) ?? {});
    onChange(JSON.stringify(next, null, 2));
  }
  const inputStyle = 'h-9 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-2 focus:ring-ring';
  function field(key: string, value: unknown, path: string[], depth = 0): React.ReactNode {
    const title = FIELD_LABELS[key] ?? key;
    const options = key === 'check' ? (node?.action.type === 'condition' ? ['element_exists', 'text_contains', 'battery_above'] : ['element_exists', 'element_gone', 'text_equals', 'text_contains', 'variable_equals', 'variable_contains', 'http_status']) : choices[key];
    if (value && typeof value === 'object' && !Array.isArray(value) && depth < 3) return <fieldset key={path.join('.')} className="space-y-3 rounded-lg border p-3"><legend className="px-1 text-xs font-medium">{title}</legend>{Object.entries(value).map(([name, nested]) => field(name, nested, [...path, name], depth + 1))}<Button size="sm" variant="ghost" onClick={() => setTab('json')}>Редактировать структуру в JSON</Button></fieldset>;
    if (Array.isArray(value) || value === null || typeof value === 'object') return <div key={path.join('.')} className="space-y-1"><p className="text-xs font-medium">{title}</p><pre className="max-h-24 overflow-auto rounded-md bg-muted p-2 text-[10px]">{JSON.stringify(value, null, 2)}</pre><Button size="sm" variant="ghost" onClick={() => setTab('json')}>Редактировать структуру в JSON</Button></div>;
    return <label key={path.join('.')} className="block space-y-1.5 text-xs"><span className="font-medium">{title} <span className="font-mono text-[10px] font-normal text-muted-foreground">{key}</span></span>
      {typeof value === 'boolean' ? <span className="flex items-center gap-2"><input type="checkbox" checked={value} disabled={!writable} onChange={event => update(path, event.target.checked)} />{value ? 'Включено' : 'Выключено'}</span>
        : options && typeof value === 'string' ? <select className={inputStyle} value={value} disabled={!writable} onChange={event => update(path, event.target.value)}>{[...new Set([value, ...options])].map(option => <option key={option} value={option}>{option}</option>)}</select>
        : ['selector', 'text', 'code', 'command', 'body'].includes(key) ? <textarea className={`${inputStyle} min-h-20 py-2 font-mono leading-5`} value={String(value)} readOnly={!writable} onChange={event => update(path, event.target.value)} />
        : <Input className="h-9 text-xs" type={typeof value === 'number' ? 'number' : 'text'} value={String(value)} readOnly={!writable} onChange={event => { if (typeof value === 'number') { if (event.target.value !== '' && Number.isFinite(Number(event.target.value))) update(path, Number(event.target.value)); } else update(path, event.target.value); }} />}
    </label>;
  }
  const template = node && ACTION_TYPES.includes(node.action.type as typeof ACTION_TYPES[number]) ? defaultAction(node.action.type as typeof ACTION_TYPES[number]) : {};
  const fields: Record<string, unknown> = node ? { ...template, ...node.action } : {};
  const spec = node && Object.hasOwn(actionContract.actions, node.action.type) ? actionContract.actions[node.action.type] : undefined;
  const optionalFields = Object.entries(spec?.fields ?? {})
    .filter(([key, rule]) => !fieldRule(rule).required && !Object.hasOwn(fields, key));
  function addParameter() {
    const raw = optionalFields.find(([name]) => name === extraField)?.[1];
    if (!raw || !writable) return;
    const rule = fieldRule(raw);
    // Only the explicit Add action materializes a value. Missing/invalid values
    // remain visible for repair; this does not manufacture execution defaults.
    const value = rule.enum?.[0] ?? (rule.type === 'object' ? {} : rule.type === 'array' ? [] : rule.type === 'boolean' ? ['fail_on_error', 'fail_if_not_found'].includes(extraField) : rule.type === 'integer' || rule.type === 'number' ? rule.min ?? 0 : '');
    update(['action', extraField], value); setExtraField('');
  }
  if (node && ['assert', 'condition'].includes(node.action.type)) {
    const parameterTemplate = parametersFor(node.action.type, String(fields.check));
    const supplied = node.action.params;
    if (parameterTemplate && (supplied === undefined || supplied !== null && typeof supplied === 'object' && !Array.isArray(supplied))) {
      // Form defaults follow the imported check. They are display-only until a
      // particular field is edited; unknown values and exact JSON types win.
      fields.params = { ...parameterTemplate, ...(supplied as Record<string, unknown> | undefined) };
    }
  }
  return <div className="space-y-4">
    {node && <ActionContractCard action={node.action} />}
    <div role="group" aria-label="Редактор параметров" className="flex gap-1 rounded-lg bg-muted p-1"><Button size="sm" variant={tab === 'fields' ? 'secondary' : 'ghost'} className="flex-1" onClick={() => setTab('fields')}><SlidersHorizontal className="mr-2 size-3" />Параметры</Button><Button size="sm" variant={tab === 'json' ? 'secondary' : 'ghost'} className="flex-1" onClick={() => setTab('json')}>JSON шага</Button></div>
    {tab === 'fields' && node ? <>
      <div className="space-y-3"><h3 className="flex items-center gap-2 text-xs font-semibold"><Settings2 className="size-3.5 text-primary" />Действие</h3>{Object.entries(fields).filter(([key]) => !['type', 'on_true', 'on_false'].includes(key)).map(([key, value]) => field(key, value, ['action', key]))}
        {Object.keys(fields).length === 1 && <p className="text-xs text-muted-foreground">У этого действия нет входных параметров.</p>}</div>
      {!!optionalFields.length && <fieldset className="space-y-2 rounded-lg border border-dashed p-3"><legend className="px-1 text-xs font-medium">Дополнительные параметры</legend><div className="flex flex-wrap gap-2"><select aria-label="Дополнительный параметр действия" className={`${inputStyle} min-w-0 flex-1`} value={optionalFields.some(([name]) => name === extraField) ? extraField : ''} disabled={!writable} onChange={event => setExtraField(event.target.value)}><option value="">Выберите параметр</option>{optionalFields.map(([name]) => <option key={name} value={name}>{FIELD_LABELS[name] ?? name} · {name}</option>)}</select><Button size="sm" variant="outline" disabled={!writable || !optionalFields.some(([name]) => name === extraField)} onClick={addParameter}>Добавить параметр</Button></div><p className="text-[11px] leading-5 text-muted-foreground">Параметр появится в JSON шага после добавления. Настройте значение и примените изменения.</p></fieldset>}
      <fieldset className="space-y-3 border-t pt-4"><legend className="flex items-center gap-2 text-xs font-semibold"><GitBranch className="size-3.5 text-primary" />Переходы</legend>
        {(node.action.type === 'condition' ? [['Да', 'on_true', true], ['Нет', 'on_false', true], ['Ошибка', 'on_failure', false]] : [['Успех', 'on_success', false], ['Ошибка', 'on_failure', false]]).map(([label, key, inAction]) => <label key={String(key)} className="block space-y-1.5 text-xs"><span>{label}</span><select className={inputStyle} disabled={!writable} value={String((inAction ? node!.action : node as unknown as Record<string, unknown>)[String(key)] ?? '')} onChange={event => update(inAction ? ['action', String(key)] : [String(key)], event.target.value || null)}><option value="">Не задан</option>{nodes.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label>)}
      </fieldset>
      <div className="grid grid-cols-2 gap-3 border-t pt-4">{field('retry', node.retry ?? 0, ['retry'])}{field('timeout_ms', node.timeout_ms ?? 30000, ['timeout_ms'])}</div>
      <p className="text-[11px] leading-5 text-muted-foreground">Шаблон задаёт поля формы. В граф попадут только применённые значения. Повторы могут повторить действие на Android.</p>
    </> : null}
    {(tab === 'json' || !node) && <div className="space-y-2"><label htmlFor="studio-node" className="text-xs font-medium">Шаг JSON: action, переходы, retry, timeout_ms</label><textarea id="studio-node" spellCheck={false} className="h-80 w-full rounded-lg border bg-background p-3 font-mono text-xs leading-5" value={source} readOnly={!writable} onChange={event => onChange(event.target.value)} /><p className="text-xs text-muted-foreground">Дополнительные поля, вложенные структуры и точные типы сохраняются. ID шага остаётся неизменным.</p></div>}
    <div className="sticky bottom-0 flex flex-wrap gap-2 border-t bg-card py-3"><Button size="sm" disabled={!writable || !pending} onClick={apply}>Применить параметры</Button><Button size="sm" variant="outline" disabled={!pending || !writable} onClick={cancel}>Отменить параметры</Button></div>
  </div>;
}
