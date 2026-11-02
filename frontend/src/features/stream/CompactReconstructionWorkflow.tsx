'use client';
import {useId,useState,type ReactNode} from 'react';
import {Check,ChevronDown,Loader2,Route} from 'lucide-react';
import {Button} from '@/components/ui/button';

export type ReconstructionWorkflowAction={label:string;disabled?:boolean;variant?:'default'|'outline'|'destructive';onClick:()=>void};
export function WorkflowDisclosure({title,children}:{title:string;children:ReactNode}){
  const [open,setOpen]=useState(false),id=useId();
  return <div className="rounded-lg border border-border bg-background/40">
    <button type="button" aria-expanded={open} aria-controls={id} className="flex min-h-10 w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={()=>setOpen(value=>!value)}>
      <span>{title}</span><ChevronDown size={14} aria-hidden="true" className={`shrink-0 transition-transform ${open?'rotate-180':''}`}/>
    </button>
    <div id={id} hidden={!open} className="space-y-3 border-t px-3 py-3">{open&&children}</div>
  </div>;
}

/** Presentation only: all processing intents remain with TeachingReconstruction. */
export function CompactReconstructionWorkflow({status,busy,sourceComplete,camerasReady,mapReady,primary,metrics,notices,attempts,advanced,surfaces,evidence}:{
  status:string;busy:boolean;sourceComplete:boolean;camerasReady:boolean;mapReady:boolean;primary?:ReconstructionWorkflowAction;
  metrics?:ReactNode;notices?:ReactNode;attempts?:ReactNode;advanced?:ReactNode;surfaces?:ReactNode;evidence?:ReactNode;
}){
  return <section aria-label="Подготовка выбранной записи" className="space-y-3 rounded-xl border border-cyan-500/25 bg-card p-3 sm:p-4">
    <header className="flex flex-col items-start gap-3">
      <div className="min-w-0 flex-1"><h4 className="flex items-center gap-2 text-sm font-semibold"><Route size={17} className="shrink-0 text-cyan-500" aria-hidden="true"/>Подготовка выбранной записи</h4>
        <p role="status" className="mt-1 flex min-h-5 items-start gap-2 text-xs text-muted-foreground">{busy&&<Loader2 size={13} aria-hidden="true" className="mt-0.5 shrink-0 animate-spin"/>}<span>{status}</span></p>
      </div>
      {primary&&<Button size="sm" className="h-auto min-h-9 whitespace-normal" variant={primary.variant??'default'} disabled={primary.disabled} onClick={primary.onClick}>{primary.label}</Button>}
    </header>
    <ol aria-label="Этапы подготовки записи" className="grid grid-cols-3 gap-2 text-[11px]">
      {[[sourceComplete,'Исходная запись'],[camerasReady,'Камеры и точки'],[mapReady,'Основная карта для проверки']].map(([done,label])=><li key={String(label)} className={`flex items-center gap-1.5 rounded-md border px-2 py-1.5 ${done?'border-emerald-500/20 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300':'border-border text-muted-foreground'}`}>
        {done?<Check size={12} aria-hidden="true" className="shrink-0"/>:<span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-current opacity-40"/>}<span>{label}</span>
      </li>)}
    </ol>
    {metrics&&<div className="text-xs tabular-nums text-muted-foreground">{metrics}</div>}
    {notices&&<div className="space-y-2 text-xs leading-5">{notices}</div>}
    <div className="grid gap-2">
      {attempts&&<WorkflowDisclosure title="Попытки и повторная обработка">{attempts}</WorkflowDisclosure>}
      {advanced&&<WorkflowDisclosure title="Дополнительно · Gaussian и настройки">{advanced}</WorkflowDisclosure>}
      {surfaces&&<WorkflowDisclosure title="Дополнительно · поверхности">{surfaces}</WorkflowDisclosure>}
      {evidence&&<WorkflowDisclosure title="Метрики, HUD и проверка качества">{evidence}</WorkflowDisclosure>}
    </div>
    <p className="text-[11px] leading-4 text-muted-foreground">Плотный рендер нужен для просмотра. Живой поток и запуск движения находятся в режиме «Направление»; эта карточка не отправляет команды в игру.</p>
  </section>;
}
