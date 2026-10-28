'use client';
import {useEffect,useRef,useState} from 'react';
import {exactRecordedFrame} from './routeMapProjection';
import {readRecordedRouteFrame,type RouteSource} from './routeSource';

export function RecordedRouteFrame({source,ticks}:{source:RouteSource;ticks:number}) {
  const canvas=useRef<HTMLCanvasElement>(null),[notice,setNotice]=useState('Декодируем опорный кадр…');
  useEffect(()=>{
    const abort=new AbortController(),target=canvas.current;
    if(!target)return;target.getContext('2d')?.clearRect(0,0,target.width,target.height);
    const index=exactRecordedFrame(source.rows,ticks);setNotice('Декодируем опорный кадр…');
    if(index===null){setNotice('Время камеры не совпало с индексом исходника.');return;}
    void readRecordedRouteFrame(source,index,target,abort.signal).then(()=>{if(!abort.signal.aborted)setNotice('Проверенный кадр исходного H.264');})
      .catch(error=>{if(!abort.signal.aborted){target.getContext('2d')?.clearRect(0,0,target.width,target.height);setNotice(error instanceof Error?error.message:'Опорный кадр недоступен.');}});
    return()=>abort.abort();
  },[source,ticks]);
  return <figure className="space-y-2 rounded-xl border border-slate-700 bg-slate-950 p-3"><figcaption className="text-xs text-slate-200">Опорный кадр записи · {(ticks/90000).toFixed(3)} с</figcaption><canvas ref={canvas} aria-label="Опорный кадр сохранённого прохода" className="aspect-video w-full rounded-lg bg-black" width={960} height={540}/><p className="text-[11px] text-slate-400">{notice}</p></figure>;
}
