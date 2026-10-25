'use client';
import {useEffect,useState} from 'react';
import {reconstructionRequest,type ReconstructionJob,type SceneAppearance} from './reconstructionClient';

export default function ReferenceComparison({job,appearance}:{job:ReconstructionJob;appearance?:SceneAppearance}) {
  const [index,setIndex]=useState(0),[urls,setUrls]=useState<string[]>([]),[error,setError]=useState<string|null>(null);
  const views=appearance?.views,available=!!views?.length;
  const selectedIndex=Math.min(index,Math.max(0,(views?.length??1)-1));
  useEffect(()=>{
    if(!available)return;const abort=new AbortController();let retired=false;const created:string[]=[];setUrls([]);setError(null);
    void Promise.all(['source','render'].map(async kind=>{
      const response=await reconstructionRequest(`/jobs/${job.id}/reference/${selectedIndex}/${kind}`,job,{signal:abort.signal});
      const blob=await response.blob();if(blob.size>4*1048576)throw Error('Слишком большой кадр сравнения.');
      if(retired)return '';const url=URL.createObjectURL(blob);created.push(url);return url;
    })).then(next=>{if(!retired)setUrls(next);}).catch(e=>{if(!retired)setError(e instanceof Error?e.message:'Не удалось открыть сравнение.');});
    return()=>{retired=true;abort.abort();created.forEach(url=>URL.revokeObjectURL(url));};
  },[available,selectedIndex,job]);
  if(!available)return <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">Качество этого результата ещё не проверено сравнением с исходными кадрами. Завершённый расчёт сам по себе не подтверждает цельную 3D-сцену.</p>;
  const view=views[selectedIndex];
  return <section aria-label="Сравнение реконструкции с исходником" className="space-y-3 rounded-xl border border-border bg-background/60 p-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h5 className="font-medium">Исходник и рендер с той же камеры</h5><p className="mt-1 text-xs text-muted-foreground">Проверка в 960 px по длинной стороне. Это записанные ракурсы; новые точки обзора и навигация отдельно не проверены.</p></div>
      <label className="text-xs">Проверяемый кадр<select aria-label="Кадр сравнения" value={selectedIndex} onChange={e=>setIndex(Number(e.target.value))} className="ml-2 rounded-md border bg-background p-2">{views.map((v,i)=><option key={v.image} value={i}>{i+1} · {v.image}</option>)}</select></label></div>
    <p role="status" className={appearance?.state==='passed'?'text-sm text-emerald-500':'text-sm text-amber-500'}>{appearance?.state==='passed'?'Базовая проверка ракурсов пройдена.':'Качество не прошло проверку. Результат доступен для диагностики.'} PSNR кадра {view.psnr.toFixed(1)} dB · SSIM {view.ssim.toFixed(3)}</p>
    {error?<p role="alert" className="text-sm text-destructive">{error}</p>:urls.length===2?<div className="grid gap-3 md:grid-cols-2">{['Исходный кадр','Рендер реконструкции'].map((label,i)=><figure key={label}><figcaption className="mb-2 text-xs text-muted-foreground">{label}</figcaption>{/* Local verified images are fetched with a per-job capability. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}<img src={urls[i]} alt={label} className="aspect-video w-full rounded-lg bg-black object-contain"/></figure>)}</div>:<p className="text-xs text-muted-foreground">Загружаем пару ракурсов…</p>}
  </section>;
}
