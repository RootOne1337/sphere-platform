'use client';
import {useEffect,useRef,useState} from 'react';
import Image from 'next/image';
export type WalkPreviewFrame={blob:Blob;points:readonly(readonly[number,number])[];sequence:number;capturedAt:number};

/** Native asynchronous image decode; no synchronous canvas/GPU readback in
 * the control loop. One displayed image, one pending decode, one latest wish. */
export function WalkLivePreview({frame,active}:{frame:WalkPreviewFrame;active:boolean}){
  const [shown,setShown]=useState<{url:string;frame:WalkPreviewFrame}|null>(null);
  const [fresh,setFresh]=useState(false);
  const latest=useRef(frame),run=useRef<(()=>void)|null>(null);latest.current=frame;
  useEffect(()=>{
    if(typeof URL.createObjectURL!=='function')return;
    let retired=false,busy=false,last=-1,current:string|null=null,pending:string|null=null;
    const next=async()=>{
      if(retired||busy||latest.current.sequence===last)return;
      busy=true;const wanted=latest.current,url=URL.createObjectURL(wanted.blob);pending=url;last=wanted.sequence;
      try{
        const image=new window.Image();image.src=url;
        await image.decode();
        if(retired)return;
        const previous=current;current=url;pending=null;setShown({url,frame:wanted});
        if(previous)URL.revokeObjectURL(previous);
      }catch{/* A failed optional preview cannot interrupt stick/camera input. */}
      finally{
        if(pending===url){pending=null;URL.revokeObjectURL(url);}
        busy=false;
        if(!retired&&latest.current.sequence!==last)void next();
      }
    };
    run.current=()=>{void next();};void next();
    return()=>{retired=true;run.current=null;if(current)URL.revokeObjectURL(current);if(pending){URL.revokeObjectURL(pending);pending=null;}};
  },[]);
  useEffect(()=>{run.current?.();},[frame]);
  useEffect(()=>{
    if(!active||!shown){setFresh(false);return;}
    const remaining=250-(performance.now()-shown.frame.capturedAt);setFresh(remaining>0);
    const timer=setTimeout(()=>setFresh(false),Math.max(0,remaining));return()=>clearTimeout(timer);
  },[active,shown]);
  return <div className="relative aspect-video w-full overflow-hidden rounded-lg border bg-black" aria-label="Проверенный кадр пешего теста">
    {shown&&<><Image src={shown.url} width={960} height={540} unoptimized alt="Исходный кадр локализации" className="h-full w-full object-contain"/>
      {active&&fresh&&shown.frame.points.length>=2&&<svg viewBox="0 0 960 540" className="pointer-events-none absolute inset-0 h-full w-full" aria-label="Направление на этом кадре">
        <polyline points={shown.frame.points.map(p=>p.join(',')).join(' ')} fill="none" stroke="#111827" strokeWidth="6" strokeLinejoin="round"/>
        <polyline points={shown.frame.points.map(p=>p.join(',')).join(' ')} fill="none" stroke="#22d3ee" strokeWidth="3" strokeLinejoin="round"/>
      </svg>}</>}
  </div>;
}
