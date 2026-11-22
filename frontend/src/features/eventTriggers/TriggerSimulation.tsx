'use client';

import { useState, type FormEvent } from 'react';
import { FlaskConical } from 'lucide-react';
import {
  Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { getApiErrorMessage } from '@/lib/apiError';
import { useSimulateEventTrigger, type EventTrigger, type TriggerSimulationResult } from '@/lib/hooks/useEventTriggers';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';

const REASON_LABEL: Record<TriggerSimulationResult['reason'], string> = {
  eligible: 'Условия допуска выполнены',
  pattern_mismatch: 'Тип события не совпадает с шаблоном',
  trigger_disabled: 'Триггер отключён',
  pipeline_unavailable: 'Пайплайн недоступен',
  cooldown: 'Действует пауза между запусками',
  hour_limit: 'Исчерпан лимит за последние 60 минут',
  duplicate_event: 'Это событие уже запустило правило',
  causal_cycle: 'Правило уже срабатывало в этой цепочке',
  depth_limit: 'Достигнута предельная глубина цепочки',
  root_limit: 'Исчерпан лимит запусков от исходного события',
  cause_unavailable: 'Происхождение события не подтверждено',
};

const utcTime = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'short', timeStyle: 'medium', timeZone: 'UTC',
});

export function TriggerSimulation({ trigger, canReadEvents }: { trigger: EventTrigger; canReadEvents: boolean }) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className="h-8 w-8"
          aria-label={`Проверить условия триггера ${trigger.name}`} title="Проверить условия">
          <FlaskConical className="h-4 w-4" aria-hidden="true" />
        </Button>
      </DialogTrigger>
      <DialogContent layout="workspace" className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Проверка условий триггера</DialogTitle>
          <DialogDescription>
            Проверка сохранённого правила «{trigger.name}». Пайплайн не запускается.
          </DialogDescription>
        </DialogHeader>
        <SimulationForm id={trigger.id} pattern={trigger.event_type_pattern} canReadEvents={canReadEvents} />
      </DialogContent>
    </Dialog>
  );
}

function SimulationForm({ id, pattern, canReadEvents }: { id: string; pattern: string; canReadEvents: boolean }) {
  const [mode, setMode] = useState<'type' | 'saved'>('type');
  const [eventType, setEventType] = useState('');
  const [eventId, setEventId] = useState('');
  const simulation = useSimulateEventTrigger();
  const saved = canReadEvents && mode === 'saved';
  const valid = saved ? /^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(eventId.trim()) : Boolean(eventType.trim());

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid || simulation.isPending) return;
    simulation.mutate(saved ? { id, eventId: eventId.trim().toLowerCase() } : { id, eventType: eventType.trim() });
  }

  return (
    <form onSubmit={handleSubmit} className="min-w-0">
      <DialogBody className="space-y-4">
        <p className="text-sm text-muted-foreground">Шаблон события <code className="break-all">{pattern}</code></p>
        {canReadEvents && <div className="space-y-1">
          <Label htmlFor="trigger-simulation-mode">Источник проверки</Label>
          <select id="trigger-simulation-mode" className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={mode} disabled={simulation.isPending} onChange={event => {
              setMode(event.target.value === 'saved' ? 'saved' : 'type');
              simulation.reset();
            }}>
            <option value="type">Тип события</option>
            <option value="saved">Сохранённое событие</option>
          </select>
        </div>}
        <div className="space-y-1">
          <Label htmlFor="trigger-simulation-event">{saved ? 'ID события' : 'Тип события'}</Label>
          {saved ? <Input id="trigger-simulation-event" className="font-mono" placeholder="UUID из журнала событий" autoComplete="off"
            maxLength={36} value={eventId} disabled={simulation.isPending}
            onChange={event => { setEventId(event.target.value); simulation.reset(); }} />
            : <Input id="trigger-simulation-event" className="font-mono" placeholder="task.completed" autoComplete="off"
              maxLength={200} value={eventType} disabled={simulation.isPending}
              onChange={event => { setEventType(event.target.value); simulation.reset(); }} />}
        </div>
        {simulation.isError && <p role="alert" className="text-sm text-destructive">
          {getApiErrorMessage(simulation.error, 'Результат проверки не подтверждён. Повторите запрос.')}
        </p>}
        {simulation.data && (canReadEvents || !simulation.data.event_id) &&
          <SimulationResult result={simulation.data} canReadEvents={canReadEvents} />}
      </DialogBody>
      <DialogFooter className="mt-4">
        <Button type="submit" disabled={!valid || simulation.isPending} aria-busy={simulation.isPending}>
          {simulation.isPending ? 'Проверяем…' : 'Проверить'}
        </Button>
      </DialogFooter>
    </form>
  );
}

function SimulationResult({ result, canReadEvents }: { result: TriggerSimulationResult; canReadEvents: boolean }) {
  return (
    <div role="status" className="space-y-2 rounded-lg border border-border bg-muted/40 p-3 text-sm">
      <div className="font-medium">
        <Badge variant={result.would_admit ? 'success' : 'secondary'}>{REASON_LABEL[result.reason]}</Badge>
      </div>
      <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1">
        <dt>Совпадение с шаблоном</dt>
        <dd>{result.matches ? 'Да' : 'Нет'}</dd>
        {result.event_id && <>
          <dt>Тип сохранённого события</dt>
          <dd className="break-all font-mono">{result.event_type}</dd>
        </>}
        {result.event_origin && <>
          <dt>Происхождение</dt>
          <dd>{result.event_origin === 'pipeline' ? 'Пайплайн' : 'Самостоятельное событие'}</dd>
        </>}
        {result.root_event_id && <>
          <dt>Исходное событие</dt>
          <dd className="max-w-44 break-all font-mono">{result.root_event_id}</dd>
        </>}
        <dt>Принятые запуски за последние 60 минут</dt>
        <dd className="tabular-nums">{result.recent_runs} / {result.max_triggers_per_hour || 'без лимита'}</dd>
        {result.cause_depth != null && <>
          <dt>Глубина цепочки</dt>
          <dd className="tabular-nums">{result.cause_depth} / {result.max_cause_depth}</dd>
        </>}
        {result.root_runs != null && <>
          <dt>Запуски от исходного события</dt>
          <dd className="tabular-nums">{result.root_runs} / {result.max_root_runs}</dd>
        </>}
        <dt>Время проверки</dt>
        <dd><time dateTime={result.observed_at}>{utcTime.format(new Date(result.observed_at))} UTC</time></dd>
        {result.retry_at && <>
          <dt>Проверить снова после</dt>
          <dd><time dateTime={result.retry_at}>{utcTime.format(new Date(result.retry_at))} UTC</time></dd>
        </>}
      </dl>
      <p className="text-xs text-muted-foreground">
        {result.event_id ? 'Доступность устройства проверяется при запуске.'
          : canReadEvents ? 'Для проверки повторов и цепочки укажите сохранённое событие.'
            : 'Проверка повторов и цепочки требует права чтения событий.'}
      </p>
    </div>
  );
}
