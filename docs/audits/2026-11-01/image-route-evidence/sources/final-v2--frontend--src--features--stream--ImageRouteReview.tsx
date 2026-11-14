'use client';
import {useEffect,useMemo,useState} from 'react';
import {Button} from '@/components/ui/button';
import {reconstructionRequest,ReconstructionResponseError,terminalReconstruction,type ReconstructionJob} from './reconstructionClient';

type Status='reference_selected'|'ambiguous'|'unknown'|'stale';
export type ImageRouteSample={source_index:number;ticks_90k:number;raw_reference_ticks_90k:number|null;raw_score:number;sequence_reference_ticks_90k:number|null;sequence_status:Status;sequence_score?:number};
export type ImageRouteReviewData={schema:'sphere-image-route-review-v1';scope:'OFFLINE_SAME_RECORDING';source_manifest_sha256:string;position_confirmed:false;arrival_confirmed:false;execution_qualified:false;reference_ticks_90k:number[];samples:ImageRouteSample[]};
const score=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=1;
const integer=(value:unknown):value is number=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0;

export function readImageRouteReview(value:unknown,manifestSha:string,frames:ReadonlyMap<number,number>):ImageRouteReviewData {
  if(!value||typeof value!=='object')throw Error('image_review_invalid');
  const data=value as ImageRouteReviewData;
  const sourceTicks=new Set(frames.values());
  if(data.schema!=='sphere-image-route-review-v1'||data.scope!=='OFFLINE_SAME_RECORDING'||data.source_manifest_sha256!==manifestSha
    ||data.position_confirmed!==false||data.arrival_confirmed!==false||data.execution_qualified!==false
    ||!Array.isArray(data.reference_ticks_90k)||data.reference_ticks_90k.length<2||data.reference_ticks_90k.length>256
    ||data.reference_ticks_90k.some((tick,i)=>!integer(tick)||!sourceTicks.has(tick)||(i>0&&tick<=data.reference_ticks_90k[i-1]))
    ||!Array.isArray(data.samples)||data.samples.length<1||data.samples.length>1024)throw Error('image_review_binding');
  const refs=new Set(data.reference_ticks_90k),seen=new Set<number>();
  for(const sample of data.samples){
    if(!sample||!integer(sample.source_index)||seen.has(sample.source_index)||!integer(sample.ticks_90k)||frames.get(sample.source_index)!==sample.ticks_90k
      ||!score(sample.raw_score)||(sample.sequence_score!==undefined&&!score(sample.sequence_score))
      ||!['reference_selected','ambiguous','unknown','stale'].includes(sample.sequence_status)
      ||(sample.raw_reference_ticks_90k!==null&&(!integer(sample.raw_reference_ticks_90k)||!refs.has(sample.raw_reference_ticks_90k)))
      ||(sample.sequence_reference_ticks_90k!==null&&(!integer(sample.sequence_reference_ticks_90k)||!refs.has(sample.sequence_reference_ticks_90k)))
      ||(sample.sequence_status==='reference_selected')!==(sample.sequence_reference_ticks_90k!==null))throw Error('image_review_sample');
    seen.add(sample.source_index);
  }
  return {...data,reference_ticks_90k:[...data.reference_ticks_90k],samples:data.samples.map(row=>({...row})).sort((a,b)=>a.ticks_90k-b.ticks_90k)};
}

const seconds=(tick:number)=>`${(tick/90000).toFixed(3)} с`;
export function ImageRouteReviewPanel({data,onSeek}:{data:ImageRouteReviewData;onSeek:(ticks:number)=>void}) {
  const [at,setAt]=useState(0),[mode,setMode]=useState<'sequence'|'raw'>('sequence');
  const samples=data.samples,current=samples[Math.min(at,samples.length-1)];
  const target=(sample:ImageRouteSample)=>mode==='sequence'?sample.sequence_reference_ticks_90k:sample.raw_reference_ticks_90k;
  const chosen=samples.filter(sample=>target(sample)!==null);
  const consistent=chosen.filter(sample=>Math.abs(target(sample)!-sample.ticks_90k)<=54000).length;
  const displaced=chosen.filter(sample=>Math.abs(target(sample)!-sample.ticks_90k)>180000).length;
  const first=Math.min(samples[0].ticks_90k,data.reference_ticks_90k[0]),last=Math.max(samples[samples.length-1].ticks_90k,data.reference_ticks_90k.at(-1)!);
  const span=Math.max(1,last-first),x=(tick:number)=>42+550*(tick-first)/span,y=(tick:number)=>162-140*(tick-first)/span;
  const seekQuery=(index:number)=>{setAt(index);onSeek(samples[index].ticks_90k);};
  const status=mode==='raw'?(target(current)===null?'Нет совпадения':'Покадровый кандидат'):
    ({reference_selected:'Опорный кадр выбран',ambiguous:'Несколько похожих участков',unknown:'Недостаточно данных',stale:'Кадр устарел'} as const)[current.sequence_status];
  return <section aria-label="Проверка сопоставления кадров" className="space-y-4 rounded-xl border border-cyan-500/25 bg-cyan-500/5 p-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-widest text-cyan-400">Проверка по видео</p><h4 className="mt-1 font-semibold">Как узнаётся участок маршрута</h4><p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">Кадры одной записи сравниваются между собой. Нажмите на график или двигайте ползунок, чтобы открыть исходный кадр.</p></div>
      <div className="flex gap-2"><Button size="sm" variant={mode==='sequence'?'secondary':'outline'} aria-pressed={mode==='sequence'} onClick={()=>setMode('sequence')}>По последовательности</Button><Button size="sm" variant={mode==='raw'?'secondary':'outline'} aria-pressed={mode==='raw'} onClick={()=>setMode('raw')}>По одному кадру</Button></div></div>
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{[['Запросов',samples.length],['Выбрано',`${chosen.length} / ${samples.length}`],['Разница ≤ 0,6 с',`${consistent} / ${samples.length}`],['Разница > 2 с',`${displaced} / ${samples.length}`]].map(([label,value])=><div key={label} className="rounded-lg border bg-background/50 p-3"><div className="text-[10px] text-muted-foreground">{label}</div><div className="mt-1 text-lg font-semibold tabular-nums">{value}</div></div>)}</div>
    <svg role="img" aria-label="Время выбранного опорного кадра относительно времени запроса" viewBox="0 0 640 205" className="w-full cursor-crosshair rounded-lg border bg-background/60" onClick={event=>{const rect=event.currentTarget.getBoundingClientRect();if(rect.width<=0)return;const tick=first+((event.clientX-rect.left)*640/rect.width-42)/550*span;const index=samples.reduce((best,s,i)=>Math.abs(s.ticks_90k-tick)<Math.abs(samples[best].ticks_90k-tick)?i:best,0);seekQuery(index);}}>
      {[0,.25,.5,.75,1].map(f=><g key={f} stroke="currentColor" opacity=".12"><line x1="42" y1={162-140*f} x2="592" y2={162-140*f}/><line x1={42+550*f} y1="22" x2={42+550*f} y2="162"/></g>)}
      <path d="M42 162 L592 22" fill="none" stroke="currentColor" strokeDasharray="4 5" opacity=".3"/>
      {samples.map((sample,i)=>{const ref=target(sample);return <circle key={sample.source_index} cx={x(sample.ticks_90k)} cy={ref===null?182:y(ref)} r={i===at?5:2.8} fill={ref===null?'#d99b46':Math.abs(ref-sample.ticks_90k)>180000?'#fb7185':'#22d3ee'} stroke={i===at?'white':'none'} strokeWidth="1.2"/>;})}
      <text x="42" y="13" fill="currentColor" fontSize="9" opacity=".65">Время найденного кадра</text><text x="42" y="198" fill="currentColor" fontSize="8" opacity=".65">{seconds(first)}</text><text x="510" y="198" fill="currentColor" fontSize="8" opacity=".65">{seconds(last)}</text><text x="460" y="173" fill="#d99b46" fontSize="8">Нет выбранного кадра</text>
    </svg>
    <label className="block text-xs">Запрос {Math.min(at+1,samples.length)} / {samples.length} · кадр {current.source_index+1} · {seconds(current.ticks_90k)}<input aria-label="Запрос сопоставления кадров" type="range" min={0} max={samples.length-1} step={1} value={Math.min(at,samples.length-1)} onChange={event=>seekQuery(Number(event.target.value))} className="mt-2 block w-full accent-cyan-400"/></label>
    <div className="flex min-h-14 flex-wrap items-center justify-between gap-3 rounded-lg border bg-background/50 p-3"><div><p className="text-sm font-medium">{status}</p><p className="mt-1 text-xs text-muted-foreground">{target(current)===null?'Сопоставление не подтверждено.':`Найденный ракурс: ${seconds(target(current)!)} · разница времени ${seconds(Math.abs(target(current)!-current.ticks_90k))}`}</p></div><div className="flex gap-2"><Button size="sm" variant="outline" onClick={()=>onSeek(current.ticks_90k)}>Открыть запрос</Button><Button size="sm" variant="outline" disabled={target(current)===null} onClick={()=>{const tick=target(current);if(tick!==null)onSeek(tick);}}>Открыть найденный ракурс</Button></div></div>
    <p className="text-[11px] leading-5 text-muted-foreground">Это временная проверка на исходной записи. График не является 3D-картой, измерением расстояния или проверкой независимого повторного проезда; команды в игру не отправляются.</p>
  </section>;
}

export default function ImageRouteReview({job,manifestSha,frames,refresh,visible,onSeek}:{job:ReconstructionJob|null;manifestSha:string|null;frames:ReadonlyMap<number,number>;refresh:number;visible:boolean;onSeek:(ticks:number)=>void}) {
  const [loaded,setLoaded]=useState<{key:string;data:ImageRouteReviewData}|null>(null);
  const [failure,setFailure]=useState<{key:string;text:string}|null>(null);
  const key=job&&manifestSha?`${job.id}:${manifestSha}`:null;
  const jobId=job?.id,jobKey=job?.key;
  const requestJob=useMemo(()=>jobId&&jobKey?[jobId,jobKey] as const:null,[jobId,jobKey]);
  useEffect(()=>{
    if(!visible||!requestJob||!manifestSha||!key||frames.size===0)return;
    const abort=new AbortController(),started=Date.now();let retired=false,polls=0,timer:ReturnType<typeof setTimeout>|undefined;setFailure(null);
    const jobCapability={id:requestJob[0],key:requestJob[1]};
    const again=()=>{if(!retired&&Date.now()-started<210000&&polls++<84)timer=setTimeout(()=>{void load();},2500);};
    const load=async()=>{
      try{
        const response=await reconstructionRequest(`/jobs/${requestJob[0]}/image-route-review`,jobCapability,{signal:abort.signal});
        const data=readImageRouteReview(await response.json(),manifestSha,frames);
        if(!retired)setLoaded({key,data});
      }catch(error){
        if(retired)return;
        setLoaded(null);
        if(error instanceof ReconstructionResponseError&&error.status===404){
          // Only observe an already running preparation. GET never launches a
          // job, and old terminal recordings do not poll indefinitely.
          try{
            const state=await(await reconstructionRequest(`/jobs/${requestJob[0]}`,jobCapability,{signal:abort.signal})).json();
            if(!retired&&typeof state?.phase==='string'&&(!terminalReconstruction(state)||['pending','running'].includes(state.image_route_review?.phase)))again();
          }catch{again();}
        }else{
          setFailure({key,text:'Диагностика сопоставления пока недоступна. Исходную запись можно просматривать.'});
          if(!(error instanceof ReconstructionResponseError)||error.status>=500||[408,429].includes(error.status))again();
        }
      }
    };
    void load();
    return()=>{retired=true;if(timer!==undefined)clearTimeout(timer);abort.abort();};
  },[requestJob,manifestSha,key,frames,refresh,visible]);
  if(!visible||!key)return null;
  if(loaded?.key===key)return <ImageRouteReviewPanel key={key} data={loaded.data} onSeek={onSeek}/>;
  return failure?.key===key?<p role="status" className="min-h-6 text-xs text-muted-foreground">{failure.text}</p>:null;
}
