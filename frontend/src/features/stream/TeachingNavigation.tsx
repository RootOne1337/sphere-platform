'use client';
import {useCallback,useEffect,useRef,useState,type RefObject} from 'react';
import {Navigation,Route,Square} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {reconstructionRequest,type NavigationState,type ReconstructionJob} from './reconstructionClient';
import {freshNavigationFrame,navigationReply,paintNavigation} from './routeNavigation';
type Binding={captureEpoch:string;width:number;height:number};
const identity=()=>crypto.randomUUID().replaceAll('-','');
export function TeachingNavigation({job,video,ready,binding}:{job:ReconstructionJob|null;video:RefObject<HTMLVideoElement|null>;ready:boolean;binding:Binding|null}) {
  const [assets,setAssets]=useState<NavigationState|null>(null),[notice,setNotice]=useState('Выберите сохранённый маршрут во вкладке «Сцена».');
  const [assetError,setAssetError]=useState(false),[assetRefresh,setAssetRefresh]=useState(0);
  const [confirmed,setConfirmed]=useState(false),[running,setRunning]=useState(false),[busy,setBusy]=useState(false),[hz,setHz]=useState(5);
  const [metrics,setMetrics]=useState({observations:0,known:0,unknown:0,late:0,age:0,compute:0,inliers:0,segment:null as number|null});
  const output=useRef<HTMLCanvasElement>(null),generation=useRef(0),session=useRef<string|null>(null),abort=useRef<AbortController|null>(null);
  const frame=useRef({sequence:0,at:0}),readyRef=useRef(ready),bindingRef=useRef(binding),stopRef=useRef<()=>void>(()=>{});
  const displayed=useRef(0);
  readyRef.current=ready;bindingRef.current=binding;
  const clear=useCallback(()=>{
    displayed.current=0;const context=output.current?.getContext('2d'),element=video.current;
    if(!context)return;
    context.clearRect(0,0,960,540);
    if(element&&readyRef.current&&freshNavigationFrame(frame.current.at,performance.now()))context.drawImage(element,0,0,960,540);
  },[video]);
  const stop=()=>{
    generation.current++;abort.current?.abort();abort.current=null;clear();setRunning(false);setBusy(false);
    const id=session.current;session.current=null;
    if(job&&id)void reconstructionRequest(`/jobs/${job.id}/navigation/stop`,job,{method:'POST',body:JSON.stringify({id})}).catch(()=>{});
  };
  stopRef.current=stop;
  useEffect(()=>()=>stopRef.current(),[]);
  useEffect(()=>{
    if(!job){setAssets(null);setAssetError(false);return;}let retired=false,timer:ReturnType<typeof setTimeout>;const request=new AbortController();
    setAssets(null);setAssetError(false);
    const poll=async()=>{try{
      const data=await(await reconstructionRequest(`/jobs/${job.id}/navigation`,job,{signal:request.signal})).json() as NavigationState;
      if(retired)return;setAssets(data);setAssetError(false);
      if(data.phase==='ready')setNotice('Карта ориентиров готова. Подключите поток и подтвердите участок для ручной проверки.');
      if(!['ready','rejected','failed','not_prepared','cancelled'].includes(data.phase))timer=setTimeout(()=>{void poll();},2000);
    }catch{if(!retired){setAssets(null);setAssetError(true);setNotice('Локальный обработчик недоступен. Запись и сохранённая сцена не изменены; повторная проверка состояния не запускает обработку.');timer=setTimeout(()=>{void poll();},10000);}}};
    void poll();return()=>{retired=true;request.abort();clearTimeout(timer);};
  },[job,assetRefresh]);
  useEffect(()=>{
    const element=video.current;if(!element?.requestVideoFrameCallback)return;
    let retired=false,callback=0;
    const next=()=>{callback=element.requestVideoFrameCallback(()=>{if(retired)return;frame.current={sequence:frame.current.sequence+1,at:performance.now()};next();});};
    next();return()=>{retired=true;element.cancelVideoFrameCallback(callback);};
  },[video,ready]);
  useEffect(()=>{
    const timer=setInterval(()=>{if(!displayed.current||frame.current.at&&performance.now()-frame.current.at>250)clear();},50);
    const hidden=()=>{if(document.hidden)stopRef.current();};
    document.addEventListener('visibilitychange',hidden);
    return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',hidden);};
  },[clear]);
  const start=async()=>{
    if(!job||!confirmed||!readyRef.current||!bindingRef.current||assets?.phase!=='ready'||session.current)return;
    const source=bindingRef.current,id=identity(),epoch=source.captureEpoch,current=++generation.current;
    const request=new AbortController();abort.current=request;session.current=id;setBusy(true);setNotice('Подтверждаем один сеанс наблюдения. Управление ИИ выключено.');
    try{
      const state=await(await reconstructionRequest(`/jobs/${job.id}/navigation/start`,job,{method:'POST',signal:request.signal,
        body:JSON.stringify({id,captureEpoch:epoch,width:source.width,height:source.height,sceneConfirmed:true})})).json();
      if(current!==generation.current)return;
      if(state.phase!=='observing'||state.id!==id||state.physicalActions!==0)throw Error('route_start_not_confirmed');
      setBusy(false);setRunning(true);setMetrics({observations:0,known:0,unknown:0,late:0,age:0,compute:0,inliers:0,segment:null});
      const scratch=document.createElement('canvas');scratch.width=960;scratch.height=540;
      const context=scratch.getContext('2d');if(!context)throw Error('canvas_unavailable');
      const deadline=performance.now()+120000;let last=0;
      const observe=async()=>{
        if(current!==generation.current||request.signal.aborted)return;
        const began=performance.now(),recent=frame.current,nowBinding=bindingRef.current;
        if(began>=deadline){stopRef.current();setNotice('120 секунд завершены. Для нового прохода запустите отдельный сеанс.');return;}
        if(!readyRef.current||nowBinding?.captureEpoch!==epoch){stopRef.current();setNotice('Поток изменился или остановился. Прежняя привязка закрыта.');return;}
        try{
          if(recent.sequence===last||!freshNavigationFrame(recent.at,began)){clear();return;}
          last=recent.sequence;context.drawImage(video.current!,0,0,960,540);
          const capturedAt=recent.at;
          const blob=await new Promise<Blob>((resolve,reject)=>scratch.toBlob(value=>value?resolve(value):reject(Error('jpeg_unavailable')),'image/jpeg',.92));
          if(blob.size>384*1024)throw Error('route_jpeg_quota');
          const jpeg=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('jpeg_unavailable'));reader.readAsDataURL(blob);});
          const digest=await crypto.subtle.digest('SHA-256',await blob.arrayBuffer());
          const sha=Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');
          if(current!==generation.current||!freshNavigationFrame(capturedAt,performance.now())){clear();return;}
          const value=await(await reconstructionRequest(`/jobs/${job.id}/navigation/observe`,job,{method:'POST',signal:request.signal,
            body:JSON.stringify({id,captureEpoch:epoch,sequence:recent.sequence,jpeg})})).json();
          if(current!==generation.current)return;
          const reply=navigationReply(value,id,epoch,recent.sequence,sha),age=performance.now()-capturedAt;
          if(!reply)throw Error('route_reply_not_bound');
          if(!freshNavigationFrame(capturedAt,performance.now())){clear();setMetrics(m=>({...m,late:m.late+1}));setNotice('Расчёт опоздал. Линия скрыта; следующий запрос возьмёт свежий кадр.');return;}
          const draw=output.current?.getContext('2d');if(draw){paintNavigation(draw,scratch,reply);displayed.current=recent.sequence;}
          // Hide this exact query result on expiry even if the raw video keeps moving.
          setTimeout(()=>{if(current===generation.current&&displayed.current===recent.sequence)clear();},Math.max(0,250-age));
          setMetrics(m=>({observations:m.observations+1,known:m.known+Number(reply.pose.state==='localized'),unknown:m.unknown+Number(reply.pose.state==='unknown'),late:m.late,age,compute:reply.computeMs,inliers:reply.pose.inliers,segment:reply.pose.segment}));
          setNotice(reply.pose.state==='localized'?'Положение камеры подтверждено. Сверяйте направление с реальной сценой.':reply.pose.state==='confirming'?'Проверяем согласованность нескольких наблюдений…':'Положение неизвестно. Направление не выдумывается.');
        }catch(error){if(current===generation.current){stopRef.current();setNotice(`Проверка остановлена: ${error instanceof Error?error.message:'нет ответа'}. Автоматического перезапуска нет.`);}}
        finally{if(current===generation.current&&!request.signal.aborted)setTimeout(()=>{void observe();},Math.max(0,1000/hz-(performance.now()-began)));}
      };
      void observe();
    }catch{if(current===generation.current){stopRef.current();setNotice('Запуск не подтверждён. Сеанс закрывается по тому же идентификатору; повтор не выполняется.');}}
  };
  return <section aria-label="Живая проверка направления" className="min-w-0 space-y-3 rounded-2xl border border-cyan-500/25 bg-gradient-to-br from-cyan-500/5 via-card to-card p-4">
    <div className="flex items-center gap-2"><Navigation className="text-cyan-400" size={20}/><h3 className="font-semibold">Направление на свежем кадре</h3><span className="ml-auto rounded-full border px-2 py-1 text-[10px] uppercase tracking-wider">Без ввода ИИ</span></div>
    <p className="text-xs leading-5 text-muted-foreground">Тот же прямой видеопоток. Одна обработка за раз, без очереди старых кадров. Линия пока описывает путь камеры, а не проверенную полосу движения.</p>
    <canvas ref={output} width={960} height={540} aria-label="Свежий кадр с направлением маршрута" className="aspect-video w-full rounded-xl border border-border bg-black"/>
    <p role="status" className="min-h-10 text-sm leading-5">{notice}</p>
    <div className="grid grid-cols-3 gap-2 text-xs tabular-nums">{[['Привязка',`${metrics.known} / ${metrics.observations}`],['Расчёт',`${metrics.compute.toFixed(1)} мс`],['Кадр → ответ',`${metrics.age.toFixed(1)} мс`],['3D-опоры',String(metrics.inliers)],['Не определено',String(metrics.unknown)],['Опоздало',String(metrics.late)]].map(([label,value])=><div key={label} className="rounded-lg border border-border p-2"><p className="text-muted-foreground">{label}</p><p className="mt-1 font-medium">{value}</p></div>)}</div>
    <p className="text-xs text-muted-foreground">Маршрут: {job?job.id.slice(0,8):'не выбран'} · карта: {assets?.phase??'не прочитана'}{metrics.segment===null?'':` · участок ${metrics.segment+1}`}</p>
    {assets?.phase!=='ready'&&<div className="rounded-xl border border-amber-500/25 bg-amber-500/5 p-3 text-xs text-amber-500"><p className="flex items-start gap-2"><Route size={15} className="shrink-0"/>{assetError?'Локальный обработчик должен быть запущен на этом компьютере.':!job?'Выберите проход во вкладке «Сцена».':'Подготовьте карту ориентиров во вкладке «Сцена».'}{assets?.error?` ${assets.error}`:''}</p>{assetError&&<Button className="mt-2" size="sm" variant="outline" onClick={()=>setAssetRefresh(n=>n+1)}>Проверить обработчик снова</Button>}</div>}
    <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={confirmed} disabled={running||busy} onChange={e=>setConfirmed(e.target.checked)}/>На экране игровой мир и записанный участок; камера и FOV соответствуют записи</label>
    <div className="flex flex-wrap items-center gap-2"><select aria-label="Частота проверки направления" className="rounded-lg border bg-background p-2 text-xs" value={hz} disabled={running||busy} onChange={e=>setHz(Number(e.target.value))}><option value={3}>3 проверки/с</option><option value={5}>5 проверок/с</option><option value={10}>10 проверок/с</option></select>
    <Button size="sm" disabled={!job||!confirmed||!ready||assets?.phase!=='ready'||running||busy} onClick={()=>{void start();}}>Проверить направление · 120 с</Button><Button variant="outline" size="sm" disabled={!running&&!busy} onClick={()=>{stop();setNotice('Наблюдение остановлено. Сохранённая карта не изменена.');}}><Square size={13} className="mr-1"/>Стоп</Button></div>
    <p className="text-[11px] leading-5 text-muted-foreground">Разрешение можно уменьшать с сохранением пропорций; FOV и режим камеры должны совпадать. Узнавание на минимальном рендере проверяется отдельно. «Кадр → ответ» измеряется в браузере; полная задержка Android неизвестна. Неподтверждённая поза и ответы старше250 мс скрывают линию. Моторная модель не запускается.</p>
  </section>;
}
