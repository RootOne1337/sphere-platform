'use client';
import {useEffect,useRef,useState} from 'react';
import {readTeachingLibrary} from './teachingLibrary';
import {runTeachingProcessingQueue,type TeachingQueueSnapshot} from './teachingQueue';

/** Owns only offline continuation. Selection, map rendering, and Android input stay separate. */
export function TeachingProcessingQueue({scope,refresh,paused=false,onSnapshot}:{scope:string|null;refresh:number;paused?:boolean;onSnapshot?:(snapshot:TeachingQueueSnapshot)=>void}){
  const changed=useRef(onSnapshot);changed.current=onSnapshot;
  const [unavailable,setUnavailable]=useState(false);
  useEffect(()=>{
    if(!scope||paused)return;
    const request=new AbortController();let retired=false;
    if(!navigator.storage?.getDirectory||!navigator.locks){setUnavailable(true);return;}
    void runTeachingProcessingQueue(scope,request.signal,async()=>{
      try{const library=await readTeachingLibrary(scope,{signal:request.signal});if(!retired)setUnavailable(false);return library.records;}
      catch(error){if(!retired)setUnavailable(true);throw error;}
    },snapshot=>{if(!retired)changed.current?.(snapshot);}).catch(()=>{/* A later mount resumes the same durable intent. */});
    return()=>{retired=true;request.abort();};
  },[scope,refresh,paused]);
  if(!scope)return null;
  if(unavailable)return <p role="status" className="rounded-lg border border-amber-500/30 p-3 text-xs text-amber-500">Автоподготовка ожидает доступ к локальному хранилищу и координации вкладок. Исходная запись сохранена; новые задания не запускаются.</p>;
  if(paused)return <p role="status" className="text-xs text-muted-foreground">Передача новых записей приостановлена на время записи или управления. Уже запущенные задания не отменяются.</p>;
  return null;
}
