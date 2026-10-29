'use client';
import {useEffect,useRef,useState} from 'react';
import {exactRecordedFrame} from './routeMapProjection';
import {readRecordedRouteFrame,type RouteSource} from './routeSource';

export function RecordedRouteFrame({source,ticks}:{source:RouteSource;ticks:number}) {
  const canvas=useRef<HTMLCanvasElement>(null),[notice,setNotice]=useState('Декодируем опорный кадр…');
  const [displayed,setDisplayed]=useState<number|null>(null),wanted=useRef(ticks),request=useRef<()=>void>(()=>{});wanted.current=ticks;
  useEffect(()=>{
    const abort=new AbortController(),target=canvas.current;let busy=false,done:number|null=null,failed:number|null=null;
    if(!target)return;target.getContext('2d')?.clearRect(0,0,target.width,target.height);
    setDisplayed(null);
    const decode=async()=>{
      if(busy||abort.signal.aborted)return;busy=true;
      try{while(!abort.signal.aborted&&wanted.current!==done&&wanted.current!==failed){
        const next=wanted.current,index=exactRecordedFrame(source.rows,next);setNotice('Декодируем опорный кадр; предыдущий проверенный кадр остаётся видимым…');
        try{
          if(index===null)throw Error('Время камеры не совпало с индексом исходника.');
          const scratch=document.createElement('canvas');
          await readRecordedRouteFrame(source,index,scratch,abort.signal);if(abort.signal.aborted)return;
          target.width=scratch.width;target.height=scratch.height;target.getContext('2d')?.drawImage(scratch,0,0);
          done=next;setDisplayed(next);setNotice('Проверенный кадр исходного H.264');
        }catch(error){if(!abort.signal.aborted){failed=next;setNotice(error instanceof Error?error.message:'Опорный кадр недоступен.');}}
      }}finally{busy=false;}
    };
    request.current=()=>{void decode();};void decode();
    return()=>{abort.abort();request.current=()=>{};};
  },[source]);
  useEffect(()=>{request.current();},[ticks,source]);
  return <figure className="space-y-2 rounded-xl border border-slate-700 bg-slate-950 p-3"><figcaption className="text-xs text-slate-200">Опорный кадр записи · {displayed===null?'ожидается':`${(displayed/90000).toFixed(3)} с`}</figcaption>{displayed!==ticks&&<p className="text-[11px] text-amber-300">Запрошен кадр {(ticks/90000).toFixed(3)} с · обновляем просмотр</p>}<canvas ref={canvas} aria-label="Опорный кадр сохранённого прохода" className="aspect-video w-full rounded-lg bg-black" width={960} height={540}/><p className="text-[11px] text-slate-400">{notice}</p></figure>;
}
