'use client';
import {useCallback,useEffect,useRef,useState,type RefObject,type ReactNode} from 'react';
import {Navigation,Route,Square} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {reconstructionRequest,type NavigationState,type ReconstructionJob,type ReconstructionState} from './reconstructionClient';
import {freshNavigationFrame,navigationReply,paintNavigation,type LiveRouteObservation} from './routeNavigation';
import {RouteNavigationDiagnostics} from './routeNavigationDiagnostics';
import {cameraMotionRequiresReview,navigationErrorLabel,navigationPhaseLabel,routeCoverageLabel,routeReadinessIssue,prepareRoute,preparationError,preparationQuotaReached} from './routePreparation';
import type {TeachingClipChoice} from './TeachingReview';
import {WalkingRoutePilot} from './WalkingRoutePilot';
import type {WalkInputControl} from './walkPilot';
import type {RouteSource} from './routeSource';
import {NavigationRouteContext} from './NavigationRouteContext';
import {saveRouteDebugReport} from './routeDebugStorage';
import {RouteDebugArchive} from './RouteDebugArchive';
type Binding={captureEpoch:string;width:number;height:number};
const identity=()=>crypto.randomUUID().replaceAll('-','');
export function TeachingNavigation({job,video,ready,binding,clips=[],clip=null,scope=null,onSelectClip,selectionDisabled=false,walkInput,onReview,sourceRecording=null}:{job:ReconstructionJob|null;video:RefObject<HTMLVideoElement|null>;ready:boolean;binding:Binding|null;clips?:TeachingClipChoice[];clip?:string|null;scope?:string|null;onSelectClip?:(id:string|null)=>void;selectionDisabled?:boolean;walkInput?:WalkInputControl;onReview?:()=>void;sourceRecording?:RouteSource|null}) {
  const [assets,setAssets]=useState<NavigationState|null>(null),[notice,setNotice]=useState('Выберите сохранённый маршрут во вкладке «Сцена».');
  const [source,setSource]=useState<ReconstructionState|null>(null),[preparing,setPreparing]=useState(false),[prepareNotice,setPrepareNotice]=useState<string|null>(null);
  const [assetError,setAssetError]=useState(false),[assetRefresh,setAssetRefresh]=useState(0);
  const [quotaJob,setQuotaJob]=useState<string|null>(null);
  const [confirmed,setConfirmed]=useState(false),[running,setRunning]=useState(false),[busy,setBusy]=useState(false),[hz,setHz]=useState(5);
  const [metrics,setMetrics]=useState({observations:0,known:0,unknown:0,late:0,age:0,compute:0,inliers:0,segment:null as number|null});
  const [diagnosticCount,setDiagnosticCount]=useState(0);
  const [walking,setWalking]=useState(false);
  const [observation,setObservation]=useState<LiveRouteObservation|null>(null);
  const [savedDebug,setSavedDebug]=useState('Диагностика сохраняется локально после остановки сеанса.');
  const [panel,setPanel]=useState<'observer'|'walk'>('observer');
  const diagnostics=useRef<RouteNavigationDiagnostics|null>(null);
  const output=useRef<HTMLCanvasElement>(null),generation=useRef(0),session=useRef<{id:string;job:ReconstructionJob;scope:string|null;clip:string|null;log:RouteNavigationDiagnostics|null}|null>(null),abort=useRef<AbortController|null>(null);
  const frame=useRef({sequence:0,at:0}),readyRef=useRef(ready),bindingRef=useRef(binding),stopRef=useRef<()=>void>(()=>{});
  const selected=useRef('');
  const displayed=useRef(0);
  selected.current=JSON.stringify([job?.id,job?.key,clip,scope,binding?.captureEpoch,binding?.width,binding?.height]);
  readyRef.current=ready;bindingRef.current=binding;
  const clear=useCallback(()=>{
    displayed.current=0;const context=output.current?.getContext('2d'),element=video.current;
    if(!context)return;
    context.clearRect(0,0,960,540);
    if(element&&readyRef.current&&freshNavigationFrame(frame.current.at,performance.now()))context.drawImage(element,0,0,960,540);
  },[video]);
  const stop=()=>{
    generation.current++;abort.current?.abort();abort.current=null;clear();setRunning(false);setBusy(false);setObservation(null);
    const active=session.current;session.current=null;
    if(active?.log&&active.scope&&active.clip){setSavedDebug('Сохраняем диагностику завершённого сеанса…');void saveRouteDebugReport(active.scope,active.clip,active.id,active.log.export())
      .then(result=>setSavedDebug(result.state==='saved'?'Диагностика сохранена в локальном архиве браузера.':result.state==='existing'?'Существующий отчёт подтверждён; повторной записи нет.':'Предыдущая запись отчёта не подтверждена; файлы сохранены для диагностики.'))
      .catch(()=>setSavedDebug('Сохранение диагностики не подтверждено. Скачайте доступный отчёт; автоматического повтора нет.'));}
    if(active)void reconstructionRequest(`/jobs/${active.job.id}/navigation/stop`,active.job,{method:'POST',body:JSON.stringify({id:active.id})}).catch(()=>{});
  };
  stopRef.current=stop;
  useEffect(()=>()=>stopRef.current(),[]);
  useEffect(()=>{
    // A scene, recording, or stream change invalidates both the old observer and
    // the user's confirmation. Close the observer on the job that opened it.
    if(session.current)stopRef.current();
    setConfirmed(false);
  },[job?.id,job?.key,clip,scope,binding?.captureEpoch,binding?.width,binding?.height]);
  useEffect(()=>{diagnostics.current=null;setDiagnosticCount(0);},[job?.id,clip,scope]);
  useEffect(()=>{setPrepareNotice(null);},[job?.id]);
  useEffect(()=>{
    if(!job){setAssets(null);setSource(null);setAssetError(false);return;}let retired=false,timer:ReturnType<typeof setTimeout>;const request=new AbortController();
    setAssets(null);setSource(null);setAssetError(false);
    const poll=async()=>{try{
      const data=await(await reconstructionRequest(`/jobs/${job.id}`,job,{signal:request.signal})).json() as ReconstructionState;
      const navigation=data.navigation??{phase:'not_prepared'};
      if(retired)return;setSource(data);setAssets(navigation);setAssetError(false);
      if(navigation.phase==='ready')setNotice('Карта ориентиров готова. Подключите поток и подтвердите участок для ручной проверки.');
      else if(data.error==='camera_quality_gate_failed')setNotice('Камеры связаны не полностью. Сначала восстановите сцену; исходная запись сохранена.');
      else setNotice(routeReadinessIssue(data,navigation)??'Проверяем состояние обработки записи.');
      // Terminal preparation can be superseded by a repaired generation. Reads
      // stay read-only and never repeat preparation or input intents.
      timer=setTimeout(()=>{void poll();},['ready','rejected','failed','not_prepared','cancelled'].includes(navigation.phase)?10000:2000);
    }catch{if(!retired){setAssets(null);setSource(null);setAssetError(true);setNotice('Локальный обработчик недоступен. Запись и сохранённая сцена не изменены; повторная проверка состояния не запускает обработку.');timer=setTimeout(()=>{void poll();},10000);}}};
    void poll();return()=>{retired=true;request.abort();clearTimeout(timer);};
  },[job,assetRefresh]);
  const prepare=async()=>{
    if(!job||!scope||!clip||preparing||!(source?.dense_available||source?.sparse_available))return;
    const selection=selected.current;setPreparing(true);setPrepareNotice(null);
    try{const result=await prepareRoute(job,scope,clip);if(selection===selected.current){setAssets(result);setAssetRefresh(n=>n+1);}}
    catch(error){if(selection===selected.current){setPrepareNotice(preparationError(error));if(preparationQuotaReached(error))setQuotaJob(job.id);setAssetRefresh(n=>n+1);}}
    finally{setPreparing(false);}
  };
  useEffect(()=>{
    // A frame from an earlier capture cannot become evidence for the new one,
    // even when the same video element/ref remains mounted during reconnect.
    frame.current={sequence:0,at:0};
    const element=video.current,epoch=binding?.captureEpoch;
    if(!ready||!epoch||!element?.requestVideoFrameCallback)return;
    let retired=false,callback=0;
    const next=()=>{callback=element.requestVideoFrameCallback(()=>{if(retired||bindingRef.current?.captureEpoch!==epoch)return;frame.current={sequence:frame.current.sequence+1,at:performance.now()};next();});};
    next();return()=>{retired=true;element.cancelVideoFrameCallback(callback);};
  },[video,ready,binding?.captureEpoch]);
  useEffect(()=>{
    const timer=setInterval(()=>{if(!displayed.current||frame.current.at&&performance.now()-frame.current.at>250)clear();},50);
    const hidden=()=>{if(document.hidden)stopRef.current();};
    document.addEventListener('visibilitychange',hidden);
    return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',hidden);};
  },[clear]);
  const start=async()=>{
    if(!job||!confirmed||!readyRef.current||!bindingRef.current||assets?.phase!=='ready'||session.current||walking)return;
    const source=bindingRef.current,id=identity(),epoch=source.captureEpoch,current=++generation.current,selection=selected.current;
    const request=new AbortController();abort.current=request;session.current={id,job,scope,clip,log:null};setBusy(true);setObservation(null);setSavedDebug('Диагностика пишется в памяти; после остановки сохранится локально.');setNotice('Подтверждаем один сеанс наблюдения. Управление ИИ выключено.');
    try{
      const state=await(await reconstructionRequest(`/jobs/${job.id}/navigation/start`,job,{method:'POST',signal:request.signal,
        body:JSON.stringify({id,captureEpoch:epoch,width:source.width,height:source.height,sceneConfirmed:true})})).json();
      if(current!==generation.current||selection!==selected.current)return;
      if(state.phase!=='observing'||state.id!==id||state.physicalActions!==0)throw Error('route_start_not_confirmed');
      setBusy(false);setRunning(true);setMetrics({observations:0,known:0,unknown:0,late:0,age:0,compute:0,inliers:0,segment:null});
      diagnostics.current=new RouteNavigationDiagnostics(job.id,clip,performance.now());setDiagnosticCount(0);
      if(session.current?.id===id)session.current.log=diagnostics.current;
      const scratch=document.createElement('canvas');scratch.width=960;scratch.height=540;
      const context=scratch.getContext('2d');if(!context)throw Error('canvas_unavailable');
      const deadline=performance.now()+120000;let last=0;
      const observe=async()=>{
        if(current!==generation.current||selection!==selected.current||request.signal.aborted)return;
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
          if(current!==generation.current||selection!==selected.current||!freshNavigationFrame(capturedAt,performance.now())){clear();return;}
          const value=await(await reconstructionRequest(`/jobs/${job.id}/navigation/observe`,job,{method:'POST',signal:request.signal,
            body:JSON.stringify({id,captureEpoch:epoch,sequence:recent.sequence,jpeg})})).json();
          if(current!==generation.current||selection!==selected.current)return;
          const reply=navigationReply(value,id,epoch,recent.sequence,sha),age=performance.now()-capturedAt;
          if(!reply)throw Error('route_reply_not_bound');
          diagnostics.current?.add(reply,capturedAt,capturedAt+age);setDiagnosticCount(diagnostics.current?.size??0);
          if(!freshNavigationFrame(capturedAt,performance.now())){clear();setMetrics(m=>({...m,late:m.late+1}));setNotice('Расчёт опоздал. Линия скрыта; следующий запрос возьмёт свежий кадр.');return;}
          setObservation({reply,capturedAt,answeredAt:capturedAt+age});
          const draw=output.current?.getContext('2d');if(draw){paintNavigation(draw,scratch,reply);displayed.current=recent.sequence;}
          // Hide this exact query result on expiry even if the raw video keeps moving.
          setTimeout(()=>{if(current===generation.current&&displayed.current===recent.sequence)clear();},Math.max(0,250-age));
          setMetrics(m=>({observations:m.observations+1,known:m.known+Number(reply.pose.state==='localized'),unknown:m.unknown+Number(reply.pose.state==='unknown'),late:m.late,age,compute:reply.computeMs,inliers:reply.pose.inliers,segment:reply.pose.segment}));
          setNotice(reply.pose.state==='localized'?'Ориентиры найдены. Сверяйте линию камеры с реальной сценой.':reply.pose.state==='confirming'?'Проверяем согласованность нескольких наблюдений…':'Положение неизвестно. Направление не выдумывается.');
        }catch(error){if(current===generation.current&&selection===selected.current){stopRef.current();setNotice(`Проверка остановлена: ${error instanceof Error?error.message:'нет ответа'}. Автоматического перезапуска нет.`);}}
        finally{if(current===generation.current&&selection===selected.current&&!request.signal.aborted)setTimeout(()=>{void observe();},Math.max(0,1000/hz-(performance.now()-began)));}
      };
      void observe();
    }catch{if(current===generation.current&&selection===selected.current){stopRef.current();setNotice('Запуск не подтверждён. Сеанс закрывается по тому же идентификатору; повтор не выполняется.');}}
  };
  const downloadDiagnostics=()=>{
    if(!diagnostics.current?.size)return;
    const file=new Blob([JSON.stringify(diagnostics.current.export(),null,2)],{type:'application/json'});
    const url=URL.createObjectURL(file),link=document.createElement('a');
    link.href=url;link.download='sphere-route-observation.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const sourceView=(view:ReactNode,visible=true)=>visible&&job&&sourceRecording?.clip===clip&&sourceRecording.scope===scope?
    <NavigationRouteContext job={job} source={sourceRecording} assetsReady={assets?.phase==='ready'} observation={observation} comparison={view} busy={running||busy||walking} preparedLandmarks={assets?.summary?.landmarks??null}/>:view;
  return <section aria-label="Живая проверка направления" className="min-w-0 space-y-4 rounded-2xl border border-cyan-500/25 bg-gradient-to-br from-cyan-500/10 via-card to-card p-4 sm:p-5">
    <div className="flex flex-wrap items-center gap-2"><span className="rounded-lg bg-cyan-500/10 p-2"><Navigation className="text-cyan-500" size={19}/></span><div className="min-w-0 flex-1"><p className="text-[10px] font-semibold uppercase tracking-[.18em] text-cyan-600 dark:text-cyan-400">Живая проверка</p><h3 className="text-base font-semibold">Направление на свежем кадре</h3></div><span className="rounded-full border border-cyan-500/25 bg-cyan-500/5 px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider">{panel==='walk'?'Эксперимент · стик':'Только наблюдение'}</span></div>
    <p className="text-xs leading-5 text-muted-foreground">Выберите запись, подключите поток и подтвердите участок. Линия показывает восстановленный путь камеры; дорога и препятствия ещё не проверены.</p>
    {onSelectClip&&<label className="block space-y-1 text-xs"><span>Сохранённый проход</span><select aria-label="Сохранённый проход для направления" value={clip??''} disabled={selectionDisabled||running||busy||preparing} onChange={e=>onSelectClip(e.target.value||null)} className="w-full rounded-lg border bg-background p-2 text-sm"><option value="">Выберите запись</option>{clips.map(item=><option key={item.id} value={item.id}>{item.title} · {item.id.slice(0,8)}{item.complete?'':' · неполная'}</option>)}</select><span className="block text-muted-foreground">Записи принадлежат этому браузеру и аккаунту; выбор не отправляет команды в игру.</span></label>}
    {walkInput&&<div className="flex gap-2" aria-label="Способ проверки маршрута"><Button size="sm" variant={panel==='observer'?'default':'outline'} disabled={running||busy||walking} onClick={()=>setPanel('observer')}>Наблюдать без ввода</Button><Button size="sm" variant={panel==='walk'?'default':'outline'} disabled={running||busy||walking} onClick={()=>setPanel('walk')}>Пеший тест со стиком</Button></div>}
    <div hidden={panel!=='observer'} className="space-y-3">
    {sourceView(<div className="overflow-hidden rounded-xl border border-border bg-black"><div className="flex items-center justify-between gap-3 bg-background/95 px-3 py-2 text-[11px]"><span className="font-medium">Живой кадр и путь камеры</span><span className={running?'text-emerald-500':'text-muted-foreground'}>{running?'Наблюдение включено':'Ожидает запуска'}</span></div><canvas ref={output} width={960} height={540} aria-label="Свежий кадр с направлением маршрута" className="aspect-video w-full"/></div>,panel==='observer')}
    <p role="status" className="rounded-lg border border-border/70 bg-background/60 px-3 py-2 text-xs leading-5">{notice}</p>
    <div className="grid grid-cols-2 gap-2 text-xs tabular-nums sm:grid-cols-3">{[['Привязка',`${metrics.known} / ${metrics.observations}`],['Расчёт',`${metrics.compute.toFixed(1)} мс`],['Кадр → ответ',`${metrics.age.toFixed(1)} мс`],['3D-опоры',String(metrics.inliers)],['Не определено',String(metrics.unknown)],['Опоздало',String(metrics.late)]].map(([label,value])=><div key={label} className="rounded-lg border border-border/70 bg-background/50 p-2.5"><p className="text-muted-foreground">{label}</p><p className="mt-1 font-semibold">{value}</p></div>)}</div>
    </div>
    <p className="text-xs text-muted-foreground">Реконструкция: {job?job.id.slice(0,8):'не выбрана'} · карта: {navigationPhaseLabel(assets?.phase)}{metrics.segment===null?'':` · участок ${metrics.segment+1}`}</p>
    {assets?.phase!=='ready'&&<div className="space-y-2 rounded-xl border border-amber-500/25 bg-amber-500/5 p-3 text-xs text-amber-500"><p className="flex items-start gap-2"><Route size={15} className="shrink-0"/>{assetError?'Локальный обработчик должен быть запущен на этом компьютере.':!job?(clip?'Для выбранного прохода ещё нет связанной сцены. Откройте «Сцена» и постройте её.':'Выберите сохранённый проход.'):source?.error==='camera_quality_gate_failed'?`Камеры связаны частично${source.quality?`: ${source.quality.registered} из ${source.quality.selected}`:''}. Ориентиры нельзя подготовить, пока сцена не восстановлена.`:!(source?.dense_available||source?.sparse_available)?'Реконструкция ещё не завершена или не прошла проверку. Откройте «Сцена» для подробностей.':cameraMotionRequiresReview(source?.camera_motion)||assets?.error==='route_camera_motion_requires_review'?'Траекторию камер нужно проверить: ориентиры для живого направления ещё не подготовлены. Откройте «Сцена» для диагностики.':assets?.phase==='pending_auto_prepare'?'Подготовка ориентиров ожидается автоматически.':assets?.error==='route_map_has_unobserved_sections'?'Сохранённая карта покрывает не весь проход. Интервалы указаны ниже.':'Подготовьте карту ориентиров для выбранного прохода.'}</p>{prepareNotice&&<p role="alert">{prepareNotice}</p>}{assets?.error&&<p>{prepareNotice?'Предыдущий результат карты':'Состояние сохранённой карты'}: {navigationErrorLabel(assets.error)}</p>}{routeCoverageLabel(assets?.summary)&&<p className="text-muted-foreground">{routeCoverageLabel(assets?.summary)}</p>}{assets?.resourceProfile&&<p className="text-muted-foreground">Профиль подготовки: {assets.resourceProfile.minRamGiB} ГиБ свободной ОЗУ · CPU, без нейросети</p>}{assets?.error==='route_map_has_unobserved_sections'&&<div className="space-y-2"><p>Повторный экспорт той же модели не восстановит пропущенные камеры. Требуется новое восстановление из сохранённого видео.</p>{onReview&&<Button size="sm" variant="outline" disabled={preparing||selectionDisabled} onClick={onReview}>Открыть восстановление камер</Button>}</div>}{assetError&&<Button size="sm" variant="outline" onClick={()=>setAssetRefresh(n=>n+1)}>Проверить обработчик снова</Button>}{job&&(source?.dense_available||source?.sparse_available)&&!cameraMotionRequiresReview(source?.camera_motion)&&assets?.error!=='route_camera_motion_requires_review'&&assets?.error!=='route_preparation_attempt_quota'&&assets?.error!=='route_map_has_unobserved_sections'&&quotaJob!==job.id&&!assetError&&['not_prepared','failed','rejected','cancelled'].includes(assets?.phase??'')&&<Button size="sm" variant="outline" disabled={preparing||selectionDisabled||!scope||!clip} onClick={()=>{void prepare();}}>{preparing?'Подготавливаем…':'Подготовить ориентиры'}</Button>}</div>}
    <div hidden={panel!=='observer'} className="space-y-3"><label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={confirmed} disabled={running||busy} onChange={e=>setConfirmed(e.target.checked)}/>На экране игровой мир и записанный участок; камера и FOV соответствуют записи</label>
    <div className="flex flex-wrap items-center gap-2"><select aria-label="Частота проверки направления" className="rounded-lg border bg-background p-2 text-xs" value={hz} disabled={running||busy} onChange={e=>setHz(Number(e.target.value))}><option value={3}>3 проверки/с</option><option value={5}>5 проверок/с</option><option value={10}>10 проверок/с</option></select>
    <Button size="sm" disabled={!job||!confirmed||!ready||assets?.phase!=='ready'||running||busy||walking} onClick={()=>{void start();}}>Проверить направление · 120 с</Button><Button variant="outline" size="sm" disabled={!running&&!busy} onClick={()=>{stop();setNotice('Наблюдение остановлено. Сохранённая карта не изменена.');}}><Square size={13} className="mr-1"/>Стоп</Button><Button variant="outline" size="sm" disabled={!diagnosticCount} onClick={downloadDiagnostics}>Скачать диагностику · {diagnosticCount}</Button></div>
    <p className="text-[11px] leading-5 text-muted-foreground">После остановки диагностика сохраняется в этом браузере. Состояния, причины, позы и задержки можно также скачать; кадры и нажатия в отчёт наблюдения не входят. Исходный маршрут сохраняется.</p>
    <p className="text-[11px] text-muted-foreground">{savedDebug}</p>
    {scope&&clip&&<RouteDebugArchive scope={scope} clip={clip} refresh={savedDebug}/>}
    {observation&&<details className="rounded-lg border p-3 text-xs" open><summary className="cursor-pointer font-medium">Диагностика последнего ответа · {observation.reply.pose.state}</summary><dl className="mt-2 grid grid-cols-2 gap-2"><div><dt>Причина</dt><dd className="break-all font-mono">{observation.reply.pose.reason}</dd></div><div><dt>Метод</dt><dd>{observation.reply.method}</dd></div><div><dt>Ошибка проекции</dt><dd>{observation.reply.pose.median_error_px?.toFixed(2)??'—'} px</dd></div><div><dt>Отклонение от пути</dt><dd>{observation.reply.pose.cross_track_units?.toFixed(3)??'—'} усл. ед.</dd></div></dl></details>}
    </div>
    {walkInput&&<div hidden={panel!=='walk'}><WalkingRoutePilot job={job} clip={clip} scope={scope} video={video} ready={ready} binding={binding} assetsReady={assets?.phase==='ready'} preparationIssue={routeReadinessIssue(source,assets)} input={walkInput} observerBusy={running||busy||panel!=='walk'} onBusyChange={setWalking} onObservation={setObservation} renderView={view=>sourceView(view,panel==='walk')}/></div>}
    <p className="text-[11px] leading-5 text-muted-foreground">Разрешение можно уменьшать с сохранением пропорций; FOV и режим камеры должны совпадать. Узнавание на минимальном рендере проверяется отдельно. «Кадр → ответ» измеряется в браузере; полная задержка Android неизвестна. Неподтверждённая поза и ответы старше 250 мс скрывают линию. Моторная модель не запускается.</p>
  </section>;
}
