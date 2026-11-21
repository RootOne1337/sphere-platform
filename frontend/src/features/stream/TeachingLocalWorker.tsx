'use client';
import {useEffect,useState} from 'react';
import {Activity,RefreshCw} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {reconstructionRequest} from './reconstructionClient';

/** Read-only health indicator. It never starts or repeats a reconstruction. */
export function TeachingLocalWorker() {
  const [state,setState]=useState<'checking'|'available'|'unavailable'>('checking');
  const [refresh,setRefresh]=useState(0);
  useEffect(()=>{
    let retired=false,request:AbortController|null=null;
    const check=async()=>{
      if(retired||document.hidden||request)return;
      const current=new AbortController();request=current;
      try{
        const response=await reconstructionRequest('/health',null,{signal:AbortSignal.any([current.signal,AbortSignal.timeout(3500)])});
        const value=await response.json();
        if(!retired)setState(value?.service==='sphere-reconstruction-v1'&&value?.one_active_job===true?'available':'unavailable');
      }catch{if(!retired)setState('unavailable');}
      finally{if(request===current)request=null;}
    };
    void check();
    const timer=setInterval(()=>{void check();},15000);
    const visibility=()=>{if(!document.hidden)void check();};
    document.addEventListener('visibilitychange',visibility);
    return()=>{retired=true;request?.abort();clearInterval(timer);document.removeEventListener('visibilitychange',visibility);};
  },[refresh]);
  return <section aria-label="Состояние локального обработчика" className={`rounded-xl border p-3 ${state==='unavailable'?'border-amber-500/30 bg-amber-500/5':'border-border bg-muted/20'}`}>
    <div className="flex flex-wrap items-center gap-2"><Activity size={16} className={state==='available'?'text-emerald-500':'text-amber-500'}/><h3 className="text-sm font-medium">Обработка сцены на этом ПК</h3><span role="status" className="text-xs text-muted-foreground">{state==='checking'?'Проверяем…':state==='available'?'Доступна':'Не подключена'}</span><Button size="sm" variant="ghost" className="ml-auto" onClick={()=>{setState('checking');setRefresh(n=>n+1);}}><RefreshCw size={14} className="mr-1"/>Проверить</Button></div>
    {state==='unavailable'&&<div className="mt-2 space-y-2 text-xs leading-5 text-muted-foreground"><p>Запись и сохранённые сцены не изменены. Обработчик нужен на компьютере, где открыт этот браузер. Его статус проверяется без повторного запуска заданий.</p><details><summary className="cursor-pointer text-foreground">Как запустить локальный обработчик</summary><p className="mt-2">Откройте PowerShell в папке проекта Sphere и выполните команду. Оставьте окно открытым на время обработки.</p><code className="mt-2 block select-all overflow-x-auto rounded-lg bg-background p-2">.\.local-pilot\motor-worker-venv\Scripts\python.exe -m scripts.pilot.reconstruction_service</code></details></div>}
  </section>;
}
