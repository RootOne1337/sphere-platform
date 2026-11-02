'use client';
import dynamic from 'next/dynamic';
import {useCallback,useEffect,useRef,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {Box,Loader2} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {boundHudTelemetry,hudChart,processingSurface,reconstructionRequest,ReconstructionResponseError,terminalReconstruction,uploadReconstruction,type ReconstructionJob,type ReconstructionState} from './reconstructionClient';
import {automaticReconstructionStopped,ensureAutomaticReconstructionLink,listReconstructionLinks,readReconstructionLink,saveReconstructionLink,stopAutomaticReconstruction,validReconstructionJob} from './reconstructionLink';
import ReferenceComparison from './ReferenceComparison';
import {cameraMotionRequiresReview,navigationErrorLabel,navigationPhaseLabel,routeCoverageLabel,prepareRoute as prepareRouteIntent,preparationError,preparationQuotaReached} from './routePreparation';
import {newAutomaticReconstruction,queueWait} from './teachingQueue';
import {assertReconstructionSource,routeSourceMismatch} from './routeSourceBinding';
import {CompactReconstructionWorkflow,type ReconstructionWorkflowAction} from './CompactReconstructionWorkflow';
import type {SceneGeometrySelection} from './sceneGeometrySelection';
const Scene=dynamic(()=>import('./ReconstructedScene'),{ssr:false,loading:()=> <p>Загружаем 3D-просмотр…</p>});
export function HudSpeedCard({telemetry,sourceManifestSha}:{telemetry:ReconstructionState['telemetry'];sourceManifestSha:string|null}){
  const data=boundHudTelemetry(telemetry,sourceManifestSha);if(!data)return null;
  const chart=data.phase==='ready'?hudChart(data.samples):null;
  const labels:Record<string,string>={processing:'Распознаём показания',failed:'Не удалось распознать показания',unavailable:'Показания недоступны',ready:'Показания игрового HUD'};
  return <div className="max-w-lg rounded-lg border border-sky-500/25 bg-sky-500/5 p-3" aria-label="Скорость на записи">
    <p className="text-sm font-medium">Скорость на записи</p>
    <p role="status" className="mt-1 text-xs text-muted-foreground">{labels[data.phase]}{data.phase==='ready'&&` · принятых: ${data.accepted_count??'—'} · неизвестно: ${data.unknown_count??'—'}`}</p>
    {chart&&<><p className="mt-1 text-xs">{chart.min}–{chart.max} км/ч · Показания игрового HUD</p><svg viewBox="0 0 300 100" role="img" aria-label="График показаний скорости; пропуски не соединены" className="mt-2 h-24 w-full">
      {chart.segments.map((segment,i)=><g key={i}>{segment.length>1&&<polyline fill="none" stroke="currentColor" strokeWidth="1.5" points={segment.map(p=>`${p.x},${p.y}`).join(' ')}/>}{segment.map((p,j)=><circle key={j} cx={p.x} cy={p.y} r="1.5" fill="currentColor"/>)}</g>)}
    </svg></>}
  </div>;
}
const phases:Record<string,string>={uploading:'Передача сохранённой записи',starting:'Запуск обработчика',verifying:'Проверка исходника и освобождения ввода',extracting:'Извлечение кадров в исходном разрешении',features:'Поиск устойчивых визуальных признаков',matching:'Сопоставление соседних ракурсов',cameras:'Восстановление связанных камер',training:'Построение плотной Gaussian-сцены на GPU',complete:'Плотная сцена готова',failed:'Обработка остановлена',cancelled:'Задание отменено'};
const reasons:Record<string,string>={no_connected_cameras_need_translation_and_overlap:'Не удалось связать камеры. Нужен проход с перемещением, перекрывающимися ракурсами и неподвижными деталями.',camera_quality_gate_failed:'Камеры восстановлены лишь частично или с большой ошибкой. Результат не принят как цельная сцена.',resource_guard:'Недостаточно ресурсов для безопасного продолжения.',worker_service_restarted:'Сервис был перезапущен. Исходная запись сохранена.',brush_failed_see_local_log:'Плотный рендер завершился с ошибкой. Камеры можно проверить отдельно.'};
reasons.brush_timing_overflow='Brush завершился с ошибкой измерения времени GPU. Камеры и проверенные промежуточные результаты сохранены.';
reasons.brush_system_timing_build_required='Совместимый локальный движок плотной сцены ещё не подготовлен. Запись и восстановленные камеры сохранены.';
phases.complete='Реконструкция рассчитана · базовая проверка ракурсов пройдена';
phases.sparse_complete='Камеры и опорные точки рассчитаны';
phases.motion_sampling='Выбор опорных кадров по движению изображения';
phases.image_route_indexing='Подготовка индекса изображений маршрута';
phases.vehicle_speed_reference='Подготовка показаний скорости для транспорта';
phases.temporal_tracking='Автоматическая проверка точек по промежуточным кадрам видео';
phases.temporal_verification='Проверка связей после удаления ложных совпадений';
phases.temporal_cameras='Автоматическое восстановление траектории по непрерывным трекам';
phases.evaluating='Сравнение рендера с исходными ракурсами';
phases.quality_rejected='Реконструкция не прошла проверку качества';
phases.review_required='Расчёт завершён · качество ещё не проверено';
phases.partial_scene='Построен фрагмент сцены · часть ракурсов не связана';
reasons.camera_geometry_degenerate='Геометрия не прошла проверку вырождения или сильных выбросов камер. Маленькая ошибка проекции здесь недостаточна; плотный этап остановлен.';
reasons.camera_intrinsics_degenerate='Расчёт дал некорректные параметры камеры. Низкая ошибка проекции не подтверждает правильность сцены; исходная запись сохранена.';
reasons.dense_visual_quality_gate_failed='Рендер недостаточно совпадает с исходными ракурсами. Эта сцена не принята как качественный результат.';
reasons.lightglue_weights_mismatch='Файл модели сопоставления не прошёл проверку целостности. Обработка остановлена.';
reasons.lightglue_source_mismatch='Версия локального инструмента сопоставления не совпадает с проверенной.';
reasons.lightglue_gpu_unavailable='GPU для сопоставления ракурсов недоступен. Запись сохранена.';
reasons.learned_matching_timeout='Сопоставление ракурсов достигло лимита времени. Промежуточные материалы сохранены.';
reasons.reference_evaluation_failed='Не удалось завершить проверку рендера по исходным ракурсам. Качество не подтверждено.';
export function TeachingReconstruction({clip,scope,folder,complete,hudHidden=false,onBusyChange,onRouteChange,visible=true,sourceManifestSha=null,selectedTicks=null,onSeekCamera,validTicks,sourcePreview,alternativeCameraCount=null,autoPrepare=false,onAutoPrepareConsumed,manageAutomaticPreparation=true,processingJobId,presentation='full',selectedGeometry,sceneContainer}:{clip:string;scope:string;folder:()=>FileSystemDirectoryHandle|null;complete:boolean;hudHidden?:boolean;onBusyChange:(busy:boolean)=>void;onRouteChange?:(job:ReconstructionJob|null)=>void;visible?:boolean;sourceManifestSha?:string|null;selectedTicks?:number|null;onSeekCamera?:(ticks:number)=>void;validTicks?:ReadonlySet<number>;sourcePreview?:ReactNode;alternativeCameraCount?:number|null;autoPrepare?:boolean;onAutoPrepareConsumed?:()=>void;manageAutomaticPreparation?:boolean;processingJobId?:string;presentation?:'full'|'compact';selectedGeometry?:SceneGeometrySelection|null;sceneContainer?:HTMLElement|null}) {
  const [job,setJob]=useState<ReconstructionJob|null>(null),[storedStatus,setStoredStatus]=useState<ReconstructionState|null>(null),[statusIdentity,setStatusIdentity]=useState<string|null>(null),[error,setError]=useState<string|null>(null);
  const jobIdentity=job?`${job.id}:${job.key}`:null;
  const status=statusIdentity===jobIdentity&&(!sourceManifestSha||storedStatus?.source_manifest_sha256===sourceManifestSha
    ||storedStatus?.phase==='uploading'&&storedStatus.source_manifest_sha256==null)?storedStatus:null;
  const setStatus=useCallback((value:ReconstructionState|null,owner:ReconstructionJob|null=job)=>{if(value)assertReconstructionSource(value,sourceManifestSha,true);setStoredStatus(value);setStatusIdentity(owner?`${owner.id}:${owner.key}`:null);},[job,sourceManifestSha]);
  const [confirmedMissing,setConfirmedMissing]=useState(false);
  const [attempts,setAttempts]=useState<ReconstructionJob[]>([]),[switchingAttempt,setSwitchingAttempt]=useState(false);
  const [preparationNotice,setPreparationNotice]=useState<{jobId:string;message:string}|null>(null),[quotaJob,setQuotaJob]=useState<string|null>(null);
  const [mask,setMask]=useState(hudHidden?'avatar':'game'),[steps,setSteps]=useState(30000),[progress,setProgress]=useState('');
  const [uploading,setUploading]=useState(false);const uploadAbort=useRef<AbortController|null>(null);
  const autoAttempted=useRef(false);
  const autoCandidate=useRef<ReconstructionJob|null>(null);
  const explicitNewAttempt=useRef(false);
  const autoStopped=useRef(false);
  const [recovering,setRecovering]=useState(true);const folderRef=useRef(folder);folderRef.current=folder;
  const [refresh,setRefresh]=useState(0),[surfaceStarting,setSurfaceStarting]=useState(false);
  const [firstView,setFirstView]=useState(0),[viewCount,setViewCount]=useState(18);
  const [selectedFragment,setSelectedFragment]=useState('legacy');
  const models=[...(status?.surface?[status.surface]:[]),...status?.fragments??[]].sort((a,b)=>(a.fragment?.first_view??0)-(b.fragment?.first_view??0));
  const selectedModel=models.find(item=>(item.id??'legacy')===selectedFragment&&item.available)??models.find(item=>item.available);
  const workingSurface=status?processingSurface(status):undefined;
  const storageKey=`sphere-reconstruction-${scope}-${clip}`;
  const sourceMismatch=error===routeSourceMismatch;
  const busy=recovering||uploading||surfaceStarting||switchingAttempt||!!job&&(!status?!confirmedMissing&&!sourceMismatch:!terminalReconstruction(status));
  const interactionBusy=manageAutomaticPreparation?busy:uploading||surfaceStarting||switchingAttempt;
  useEffect(()=>{onBusyChange(interactionBusy);},[interactionBusy,onBusyChange]);
  const sourceBound=!sourceManifestSha||status?.source_manifest_sha256===sourceManifestSha;
  useEffect(()=>{onRouteChange?.(sourceBound?job:null);},[job,sourceBound,onRouteChange]);
  useEffect(()=>{autoStopped.current=false;setConfirmedMissing(false);},[job?.id]);
  useEffect(()=>()=>{uploadAbort.current?.abort();onBusyChange(false);},[onBusyChange]);
  useEffect(()=>{
    let retired=false;setRecovering(true);
    void(async()=>{
      const source=folderRef.current();let saved=source?await readReconstructionLink(source,clip):null;
      if(!saved){const previous=JSON.parse(sessionStorage.getItem(storageKey)??'null');if(validReconstructionJob(previous)){saved=previous;if(source)await saveReconstructionLink(source,clip,saved);}}
      const available=source?await listReconstructionLinks(source,clip):saved?[saved]:[];
      if(!saved&&available.length===1&&available[0].creation)saved=available[0];
      if(!retired){setAttempts(available);if(saved)setJob(current=>processingJobId&&saved?.id===processingJobId?saved:current??saved);setRecovering(false);}
    })().catch(()=>{if(!retired){setError('Не удалось восстановить локальную ссылку на сцену. Исходная запись сохранена.');setRecovering(false);}});
    return()=>{retired=true;};
  },[storageKey,clip,processingJobId]);
  useEffect(()=>{
    if(!job)return;let retired=false;let timer:ReturnType<typeof setTimeout>;const abort=new AbortController();
    let delay=1000;
    const poll=async()=>{try{
      // The explicit initial upload owns its AbortController. Its new durable
      // intent may already be rendered, but readback must not race that write.
      if(uploadAbort.current&&uploadAbort.current!==abort){timer=setTimeout(()=>{void poll();},500);return;}
      const source=folderRef.current();
      if(job.creation&&source&&(autoStopped.current||await automaticReconstructionStopped(source,job)))autoStopped.current=true;
      // A creation record is an already authorized durable continuation. The
      // checkbox controls creating a NEW automatic intent, not recovering one.
      const automatic=manageAutomaticPreparation&&!!job.creation&&complete&&!autoStopped.current;
      let next:ReconstructionState;
      try{next=await(await reconstructionRequest(`/jobs/${job.id}`,job,{signal:abort.signal})).json();if(!retired)setConfirmedMissing(false);}
      catch(e){
        if(e instanceof ReconstructionResponseError&&e.status===404&&!retired)setConfirmedMissing(true);
        if(!automatic||!source||!(e instanceof ReconstructionResponseError)||e.status!==404)throw e;
        // Only a confirmed absence permits repeating the same durable POST.
        if(retired||autoStopped.current||await automaticReconstructionStopped(source,job))return;
        setConfirmedMissing(false);
        try{next=await(await reconstructionRequest('/jobs',null,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:job.id,key:job.key,...job.creation}),signal:abort.signal})).json();}
        catch(createError){if(createError instanceof ReconstructionResponseError&&createError.status===409&&['resource_guard','one_active_job_only'].includes(createError.message)&&!retired)setConfirmedMissing(true);throw createError;}
      }
      assertReconstructionSource(next,sourceManifestSha,true);
      if(retired)return;setStatus(next);setError(null);if(next.phase!=='uploading')delay=1000;
      if(automatic&&source&&next.phase==='uploading'){
        if(!navigator.locks)throw Error('reconstruction_lock_unavailable');
        await navigator.locks.request(`sphere-reconstruction-upload-${job.id}`,{ifAvailable:true},async lock=>{
          if(!lock||retired||autoStopped.current||await automaticReconstructionStopped(source,job))return;
          const before=await(await reconstructionRequest(`/jobs/${job.id}`,job,{signal:abort.signal})).json() as ReconstructionState;
          assertReconstructionSource(before,sourceManifestSha,true);
          if(before.phase!=='uploading'){if(!retired)setStatus(before);return;}
          setUploading(true);uploadAbort.current=abort;
          try{
            await uploadReconstruction(source,job,(bytes,total)=>setProgress(`${(bytes/1048576).toFixed(1)} / ${(total/1048576).toFixed(1)} МБ`),abort.signal);
            const confirmed=await(await reconstructionRequest(`/jobs/${job.id}`,job,{signal:abort.signal})).json() as ReconstructionState;
            assertReconstructionSource(confirmed,sourceManifestSha,true);
            if(!retired&&!autoStopped.current&&confirmed.phase==='uploading'&&!await automaticReconstructionStopped(source,job)){
              next=await(await reconstructionRequest(`/jobs/${job.id}/start`,job,{method:'POST',body:'{}',signal:abort.signal})).json();
              assertReconstructionSource(next,sourceManifestSha);
              if(!retired)setStatus(next);
            }else next=confirmed;
          }finally{uploadAbort.current=null;if(!retired)setUploading(false);}
        });
      }
      if(!retired&&(!terminalReconstruction(next)||next.telemetry?.phase==='processing'))timer=setTimeout(()=>{void poll();},2500);
    }catch(e){if(!retired){
      if(e instanceof Error&&e.message===routeSourceMismatch){setStatus(null);setError(routeSourceMismatch);return;}
      if(autoStopped.current){setError('Автоматическая подготовка остановлена. Состояние задания проверяется.');if(!(e instanceof ReconstructionResponseError&&e.status===404))timer=setTimeout(()=>{void poll();},10000);return;}
      const fatal=e instanceof ReconstructionResponseError&&[400,403,422].includes(e.status)||e instanceof ReconstructionResponseError&&e.status===409&&!['job_not_found','resource_guard','one_active_job_only','upload_offset_mismatch_read_offsets_before_retry'].includes(e.message)||e instanceof DOMException&&e.name==='NotFoundError'||e instanceof Error&&['source_file_quota','invalid_worker_offset','reconstruction_lock_unavailable'].includes(e.message);
      if(fatal&&job.creation&&folderRef.current()){autoStopped.current=true;await stopAutomaticReconstruction(folderRef.current()!,job).catch(()=>{});}
      const message=e instanceof Error?e.message:'нет ответа';
      setError(fatal?`Подготовка остановлена: ${message}. Запись сохранена.`:
        message==='resource_guard'?'Недостаточно ресурсов. Подготовка продолжится автоматически, когда они освободятся.':
        message==='one_active_job_only'?'Другая обработка ещё выполняется. Подготовка продолжится автоматически после её завершения.':
        `Подготовка ожидает локальный обработчик: ${message}. Проверяем то же задание.`);
      if(!fatal){timer=setTimeout(()=>{void poll();},delay);delay=Math.min(delay*2,30000);}
    }}};
    void poll();return()=>{retired=true;abort.abort();clearTimeout(timer);};
  },[job,refresh,autoPrepare,complete,manageAutomaticPreparation,sourceManifestSha,setStatus]);
  const start=async(routeOnly=false,candidateJob?:ReconstructionJob)=>{
    const source=folder();if(!source||uploadAbort.current)return;
    const controller=new AbortController();uploadAbort.current=controller;setConfirmedMissing(false);setUploading(true);setError(null);
    let pending:ReconstructionJob|null=null;
    try{
      let next=candidateJob??job;
      if(!next&&routeOnly){
        autoCandidate.current??={...newAutomaticReconstruction(mask as 'none'|'avatar'|'game'),creation:{mask:mask as 'none'|'avatar'|'game',steps,prepare_route:true,route_only:true}};
        next=explicitNewAttempt.current?autoCandidate.current:await ensureAutomaticReconstructionLink(source,clip,autoCandidate.current.creation!.mask,autoCandidate.current);
        if(!next)throw Error('reconstruction_attempt_selection_required');
      }
      next??={id:crypto.randomUUID().replaceAll('-',''),key:Array.from(crypto.getRandomValues(new Uint8Array(32)),v=>v.toString(16).padStart(2,'0')).join('')};
      // saveReconstructionLink confirms immutable OLD + NEW attempt links
      // before replacing the current pointer. No HTTP precedes this commit.
      await saveReconstructionLink(source,clip,next);pending=next;autoStopped.current=false;
      explicitNewAttempt.current=false;
      setStatus(null);setJob(next);setAttempts(await listReconstructionLinks(source,clip));sessionStorage.setItem(storageKey,JSON.stringify(next));
      const launch=async()=>{
        if(controller.signal.aborted)throw new DOMException('Aborted','AbortError');
        const options=next.creation??{mask,steps,prepare_route:true,route_only:routeOnly};
        const created=await(await reconstructionRequest('/jobs',null,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:next.id,key:next.key,...options}),signal:controller.signal})).json();assertReconstructionSource(created,sourceManifestSha,true);setStatus(created,next);
        if(created.phase!=='uploading')return;
        await uploadReconstruction(source,next,(bytes,total)=>setProgress(`${(bytes/1048576).toFixed(1)} / ${(total/1048576).toFixed(1)} МБ`),controller.signal);
        const confirmed=await(await reconstructionRequest(`/jobs/${next.id}`,next,{signal:controller.signal})).json() as ReconstructionState;
        assertReconstructionSource(confirmed,sourceManifestSha,true);
        if(confirmed.phase!=='uploading'){setStatus(confirmed,next);return;}
        const started=await(await reconstructionRequest(`/jobs/${next.id}/start`,next,{method:'POST',body:'{}',signal:controller.signal})).json();assertReconstructionSource(started,sourceManifestSha);setStatus(started,next);
      };
      if(navigator.locks)await navigator.locks.request(`sphere-reconstruction-upload-${next.id}`,{signal:controller.signal},launch);else await launch();
    }catch(e){if(pending){setJob(pending);setError(`Запуск не подтверждён: ${e instanceof Error?e.message:'нет ответа'}. Проверяем существующее задание; повторного запуска нет.`);}else setError('Не удалось сохранить ссылку на новое задание. Обработка не запускалась; прежняя попытка и исходная запись сохранены.');}
    finally{uploadAbort.current=null;setUploading(false);}
  };
  const retryPreparation=()=>{
    if(!job||!status||!['failed','cancelled'].includes(status.phase)||busy||!complete||!folder()||uploadAbort.current)return;
    const next:ReconstructionJob={id:crypto.randomUUID().replaceAll('-',''),key:Array.from(crypto.getRandomValues(new Uint8Array(32)),v=>v.toString(16).padStart(2,'0')).join(''),
      creation:{mask:hudHidden?'avatar':'game',steps:30000,prepare_route:true,route_only:true}};
    if(next.id===job.id||attempts.some(item=>item.id===next.id)){setError('Не удалось создать отдельную попытку. Прежняя запись и результат сохранены.');return;}
    void start(true,next);
  };
  const selectAttempt=async(id:string)=>{
    const source=folder(),selected=attempts.find(item=>item.id===id);
    if(!source||!selected||busy||id===job?.id)return;
    setSwitchingAttempt(true);setError(null);
    try{
      await saveReconstructionLink(source,clip,selected);
      explicitNewAttempt.current=false;autoCandidate.current=null;
      sessionStorage.setItem(storageKey,JSON.stringify(selected));
      setStatus(null);setJob(selected);
    }catch{setError('Не удалось выбрать сохранённую попытку. Предыдущие ссылки и исходная запись сохранены.');}
    finally{setSwitchingAttempt(false);}
  };
  useEffect(()=>{
    if(!manageAutomaticPreparation||!autoPrepare||autoAttempted.current||recovering||!complete||!folderRef.current())return;
    autoAttempted.current=true;
    // A recovered link belongs to an existing intent, including an ambiguous
    // start. Only new completed recordings may create an automatic attempt.
    if(job||attempts.length){onAutoPrepareConsumed?.();return;}
    const source=folderRef.current()!,request=new AbortController();let retired=false;setUploading(true);
    const mask=hudHidden?'avatar':'game';autoCandidate.current??=newAutomaticReconstruction(mask);
    void(async()=>{
      for(let attempt=0;attempt<3;attempt++){
        try{
          const next=await ensureAutomaticReconstructionLink(source,clip,mask,autoCandidate.current!);
          if(retired)return;
          if(next){setUploading(false);setJob(next);setAttempts([next]);sessionStorage.setItem(storageKey,JSON.stringify(next));onAutoPrepareConsumed?.();}
          return;
        }catch(error){
          if(retired)return;
          if(attempt===2){setError(`Не удалось сохранить автоматическую подготовку: ${error instanceof Error?error.message:'ошибка'}. Запись сохранена.`);return;}
          await queueWait(1000*(attempt+1),request.signal);
        }
      }
    })().catch(()=>{}).finally(()=>{if(!retired)setUploading(false);});
    return()=>{retired=true;request.abort();};
  },[autoPrepare,recovering,complete,job,attempts,onAutoPrepareConsumed,clip,hudHidden,storageKey,manageAutomaticPreparation]);
  const cancel=async()=>{
    if(job?.creation)autoStopped.current=true;uploadAbort.current?.abort();if(!job)return;
    if(job.creation&&folderRef.current())try{await stopAutomaticReconstruction(folderRef.current()!,job);}catch{setError('Не удалось сохранить остановку подготовки. Проверьте локальное хранилище.');return;}
    const surface=status?processingSurface(status):undefined;
    try{setStatus(await(await reconstructionRequest(`/jobs/${job.id}/${surface?(surface.id?`fragments/${surface.id}/cancel`:'surface/cancel'):'cancel'}`,job,{method:'POST',body:'{}'})).json());setRefresh(n=>n+1);}catch{setError('Отмена не подтверждена. Состояние проверяется; управление остаётся заблокировано.');setRefresh(n=>n+1);}
  };
  const stopWaiting=async()=>{
    const source=folderRef.current();if(!job?.creation||!source)return;autoStopped.current=true;
    try{await stopAutomaticReconstruction(source,job);setError(confirmedMissing?'Ожидание подготовки остановлено.':'Ожидание остановлено; проверяем, было ли задание создано.');setRefresh(n=>n+1);}
    catch{setError('Не удалось сохранить остановку подготовки. Проверьте локальное хранилище.');}
  };
  const startSurface=async()=>{
    if(!job||surfaceStarting)return;setSurfaceStarting(true);setError(null);
    try{const id=crypto.randomUUID().replaceAll('-','');setStatus(await(await reconstructionRequest(`/jobs/${job.id}/fragments/${id}/start`,job,{method:'POST',body:JSON.stringify({first_view:firstView,view_count:Math.min(viewCount,(status?.quality?.registered??18)-firstView)})})).json());}
    catch(e){setError(`Построение поверхностей не подтверждено: ${e instanceof Error?e.message:'нет ответа'}. Проверяем то же задание.`);}
    finally{setSurfaceStarting(false);setRefresh(n=>n+1);}
  };
  const prepareRoute=async()=>{
    if(!job||busy)return;setSurfaceStarting(true);setPreparationNotice(null);
    try{const navigation=await prepareRouteIntent(job,scope,clip);
      if(status)setStatus({...status,navigation});
    }catch(e){setPreparationNotice({jobId:job.id,message:preparationError(e)});if(preparationQuotaReached(e))setQuotaJob(job.id);}
    finally{setSurfaceStarting(false);setRefresh(n=>n+1);}
  };
  const surfaceLabels:Record<string,string>={starting:'Подготовка 3D-модели',preparing:'Проверка камер и оригинальных кадров',densifying:'Многовидовое восстановление глубины',meshing:'Построение треугольных поверхностей',baking:'Проекция фотографий на видимые поверхности',ready:'Текстурированная 3D-модель сохранена',review_required:'Пробная модель сохранена · проверьте поверхности визуально',failed:'Построение модели остановлено',cancelled:'Построение модели отменено'};
  const navigationBusy=['pending_auto_prepare','preparing','features'].includes(status?.navigation?.phase??'');
  const canPrepareMap=!!job&&!!status?.geometry_available&&!busy&&!!(status.dense_available||status.sparse_available)
    &&!cameraMotionRequiresReview(status.camera_motion)&&!['route_camera_motion_requires_review','route_preparation_attempt_quota','route_map_has_unobserved_sections'].includes(status.navigation?.error??'')
    &&quotaJob!==job.id&&status.navigation?.phase!=='ready';
  const newAttempt=()=>{explicitNewAttempt.current=true;autoCandidate.current=null;sessionStorage.removeItem(storageKey);setJob(null);setStatus(null);setError(null);};
  const sceneNode=visible&&job&&(selectedGeometry!==undefined||status?.geometry_available)?<Scene job={job} status={{...status??{phase:'review_required'},surface:selectedModel??status?.surface}} sourceManifestSha={sourceManifestSha} selectedTicks={selectedTicks} onSeekCamera={onSeekCamera} validTicks={validTicks} sourcePreview={sourcePreview} showGeometryMap={alternativeCameraCount===null} sourceKey={`${scope}:${clip}`} selectedGeometry={selectedGeometry}/>:null;
  const scene=sceneContainer===undefined?sceneNode:sceneContainer?createPortal(sceneNode,sceneContainer):null;
  if(presentation==='compact'){
    const sourceBound=!!sourceManifestSha&&status?.source_manifest_sha256===sourceManifestSha;
    const mapConfirmed=sourceBound&&status?.navigation?.phase==='ready'&&!cameraMotionRequiresReview(status.camera_motion);
    const selectedPreview=selectedGeometry&&selectedGeometry.id!=='primary'&&selectedGeometry.sourceKey===`${scope}:${clip}`
      &&selectedGeometry.jobId===job?.id&&!!sourceManifestSha&&selectedGeometry.sourceManifestSha===sourceManifestSha
      &&selectedGeometry.geometry?.source_manifest_sha256===sourceManifestSha&&Array.isArray(selectedGeometry.geometry.cameras)&&Array.isArray(selectedGeometry.geometry.points)
      &&typeof selectedGeometry.label==='string'&&selectedGeometry.label.length<=256?selectedGeometry:null;
    let primary:ReconstructionWorkflowAction|undefined;
    if(!recovering){
      if(sourceMismatch)primary={label:'Проверить состояние',variant:'outline',onClick:()=>setRefresh(value=>value+1)};
      else if(job?.creation&&!status&&!autoStopped.current)primary={label:'Остановить ожидание',variant:'outline',onClick:()=>{void stopWaiting();}};
      else if(status?.phase==='uploading'&&!uploading)primary={label:'Продолжить передачу',onClick:()=>{void start();}};
      else if(job&&busy&&!navigationBusy)primary={label:'Отменить обработку',variant:'outline',onClick:()=>{void cancel();}};
      else if(canPrepareMap)primary={label:'Подготовить карту',onClick:()=>{void prepareRoute();}};
      else if(!status&&!job?.creation)primary={label:'Подготовить ориентиры',disabled:!complete||busy,onClick:()=>{void start(true);}};
      else if(mapConfirmed)primary={label:'Карта подготовлена',disabled:true,onClick:()=>{}};
      else if(job&&!busy)primary={label:'Проверить состояние',variant:'outline',onClick:()=>setRefresh(value=>value+1)};
    }
    const workflowStatus=recovering?'Проверяем сохранённую обработку…':workingSurface?(surfaceLabels[workingSurface.phase]??workingSurface.phase):navigationBusy?`Камеры рассчитаны · ${navigationPhaseLabel(status?.navigation?.phase)}`:status?(phases[status.phase]??status.phase):job?.creation?autoStopped.current?'Автоматическая подготовка остановлена.':'Ожидаем локальный обработчик; сохранённая подготовка продолжится автоматически.':complete?'Исходная запись сохранена. Подготовьте камеры и карту.':'Исходная запись не подтверждена; обработка недоступна.';
    return <><CompactReconstructionWorkflow status={workflowStatus+(uploading&&progress?` · ${progress}`:'')} busy={busy} sourceComplete={complete}
      camerasReady={sourceBound&&!!(status?.sparse_available||status?.dense_available)} mapReady={mapConfirmed} primary={primary}
      metrics={<>{status?.quality&&<p>Основная попытка: {status.quality.registered}/{status.quality.selected} камер · {status.quality.points?.toLocaleString('ru')??'—'} точек · ошибка {status.quality.mean_reprojection_px.toFixed(2)} px</p>}
        {selectedPreview&&<p className="mt-1 text-cyan-700 dark:text-cyan-300">Выбранный просмотр: {selectedPreview.label} · {selectedPreview.geometry!.cameras.length} камер · {selectedPreview.geometry!.points.length.toLocaleString('ru')} точек</p>}
        {routeCoverageLabel(status?.navigation?.summary)&&<p className="mt-1">Основная карта: {routeCoverageLabel(status?.navigation?.summary)}</p>}</>}
      notices={<>
        {error&&<p role="alert" className="text-destructive">{error}</p>}
        {preparationNotice&&preparationNotice.jobId===job?.id&&<p role="alert" className="text-destructive">{preparationNotice.message}</p>}
        {status?.error&&<p role="alert" className="text-destructive">{reasons[status.error]??status.error} Исходное видео сохранено.</p>}
        {status?.navigation?.error&&<p role="status" className="text-amber-600 dark:text-amber-400">Карта: {navigationErrorLabel(status.navigation.error)}.</p>}
        {cameraMotionRequiresReview(status?.camera_motion)&&<p role="status" className="text-amber-600 dark:text-amber-400">Траектория камер требует проверки. Движение по этой версии карты выключено.</p>}
        {status?.dense_partial_available&&status.checkpoint&&<p role="status">Промежуточный рендер: {status.checkpoint.steps}/{status.checkpoint.target_steps} итераций. Расчёт ещё не завершён.</p>}
        {models.filter(item=>item.error).map(item=><p key={item.id??'legacy'} role="alert" className="text-destructive">Поверхности: {reasons[item.error!]??item.error}. Предыдущие результаты сохранены.</p>)}
      </>}
      attempts={<>
        {attempts.length>0&&<label className="block text-xs">Сохранённая попытка реконструкции<select aria-label="Сохранённая попытка реконструкции" className="mt-1 block w-full rounded-md border bg-background p-2" value={job?.id??''} disabled={busy||!folder()} onChange={event=>{void selectAttempt(event.target.value);}}>{!job&&<option value="">Новое задание</option>}{attempts.map((item,index)=><option key={item.id} value={item.id}>Попытка {index+1} · {item.id.slice(0,8)}</option>)}</select></label>}
        <p className="text-xs text-muted-foreground">Выбор открывает сохранённый результат. Повторная обработка создаёт отдельную попытку и сохраняет прежний результат.</p>
        <div className="flex flex-wrap gap-2">{status&&['failed','cancelled'].includes(status.phase)?<Button size="sm" variant="outline" disabled={busy||!complete||!folder()} onClick={retryPreparation}>Повторить подготовку записи</Button>:status&&terminalReconstruction(status)&&<Button size="sm" variant="outline" onClick={newAttempt}>Новое отдельное задание</Button>}
          {job&&busy&&!navigationBusy&&primary?.label!=='Отменить обработку'&&<Button size="sm" variant="outline" onClick={()=>{void cancel();}}>Отменить обработку</Button>}
          {job&&<Button size="sm" variant="outline" disabled={uploading||surfaceStarting} onClick={()=>setRefresh(value=>value+1)}>Проверить состояние</Button>}
        </div>
      </>}
      advanced={<>
        <p className="text-xs text-muted-foreground">Gaussian — дополнительный визуальный рендер. Камеры и карта рассчитываются отдельным быстрым этапом.</p>
        <div className="grid gap-3 sm:grid-cols-2"><label className="text-xs">Маска записи<select className="mt-1 block w-full rounded-md border bg-background p-2" value={mask} disabled={!!status||busy} onChange={event=>setMask(event.target.value)}><option value="game">HUD и персонаж в центре</option><option value="avatar">Персонаж · HUD уже скрыт</option><option value="none">Без маски · свободный вид от первого лица</option></select></label>
          <label className="text-xs">Качество обработки<select className="mt-1 block w-full rounded-md border bg-background p-2" value={steps} disabled={!!status||busy} onChange={event=>setSteps(Number(event.target.value))}><option value={3000}>Проба · 3 000 шагов</option><option value={5000}>Стандарт · 5 000 шагов</option><option value={10000}>Детальнее · 10 000 шагов</option><option value={30000}>Высокая детализация · 30 000 шагов</option></select></label></div>
        <Button size="sm" variant="outline" disabled={!complete||busy||!!status} onClick={()=>{void start(false);}}>Построить 3D-сцену</Button>
        {status&&<p className="text-xs text-muted-foreground">Для другого рендера сначала создайте новую попытку в разделе «Попытки и повторная обработка».</p>}
      </>}
      surfaces={job&&status?.geometry_available?<>
        <p className="text-xs text-muted-foreground">Фотографическая сетка сохраняется отдельно. Невидимые участки остаются пустыми.</p>
        <Button size="sm" variant="outline" disabled={busy||!status.dense_available||!status.surface_supported||!terminalReconstruction(status)} onClick={()=>{void startSurface();}}>{models.length?'Построить другой фрагмент':'Построить поверхности'}</Button>
        <div className="flex flex-wrap items-end gap-3"><label className="text-xs">Начальный ракурс<input aria-label="Начальный ракурс фрагмента" disabled={busy} className="mt-1 block w-24 rounded-md border bg-background p-2" type="number" min={1} max={Math.max(1,(status.quality?.registered??18)-2)} value={firstView+1} onChange={event=>setFirstView(Math.max(0,Math.min((status.quality?.registered??18)-3,Number(event.target.value)-1)))}/></label><label className="text-xs">Длина фрагмента<select disabled={busy} className="mt-1 block rounded-md border bg-background p-2" value={viewCount} onChange={event=>setViewCount(Number(event.target.value))}><option value={12}>12 ракурсов</option><option value={18}>18 ракурсов</option><option value={24}>24 ракурса</option></select></label></div>
        {models.length>0&&<label className="block text-xs">Сохранённый фрагмент маршрута<select aria-label="Сохранённый фрагмент маршрута" className="mt-1 block w-full rounded-md border bg-background p-2" value={selectedModel?.id??'legacy'} onChange={event=>setSelectedFragment(event.target.value)}>{models.map((item,index)=><option key={item.id??'legacy'} value={item.id??'legacy'} disabled={!item.available}>Участок {index+1}{item.fragment?` · ракурсы ${item.fragment.first_view+1}–${item.fragment.first_view+item.fragment.view_count}`:''} · {surfaceLabels[item.phase]??item.phase}</option>)}</select></label>}
        {workingSurface&&<p role="status" className="text-xs">{surfaceLabels[workingSurface.phase]??workingSurface.phase}{workingSurface.total_views?` · ${workingSurface.views}/${workingSurface.total_views} ракурсов`:''}</p>}
        {selectedModel?.phase==='review_required'&&<p className="text-xs text-amber-600 dark:text-amber-400">Проверьте поверхности визуально: это пробная модель.</p>}
        {selectedModel?.visual_review?.state==='issues_found'&&<p className="text-xs text-amber-600 dark:text-amber-400">В поверхностях найдены дефекты: {selectedModel.visual_review.issues.map(issue=>({holes:'пропуски',occluding_surfaces:'ложные перекрытия',stretched_triangles:'растянутые треугольники',pose_inconsistency:'сомнительные камеры'})[issue]??issue).join(', ')}.</p>}
        {selectedModel?.result&&<p className="text-xs">{selectedModel.result.triangles.toLocaleString('ru')} треугольников · {selectedModel.result.textures} фотографий · {(selectedModel.result.bytes/1048576).toFixed(1)} МБ · без покрытия: {selectedModel.result.unknown_faces.toLocaleString('ru')} граней</p>}
        {!status.surface_supported&&!status.surface&&<p className="text-xs text-muted-foreground">Локальный инструмент OpenMVS CPU ещё не подготовлен.</p>}
      </>:undefined}
      evidence={<><HudSpeedCard telemetry={status?.telemetry} sourceManifestSha={sourceManifestSha}/>
        <p className="text-xs text-muted-foreground">Масштаб сцены в метрах не подтверждён. Количество точек и ошибка проекции не доказывают качество дороги или готовность автоматического движения.</p>
        {visible&&job&&status?.dense_available&&<ReferenceComparison job={job} appearance={status.appearance}/>}
      </>}/>{scene}</>;
  }
  return <section aria-label="Построение плотной 3D-сцены" className="space-y-4 rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/5 via-card to-sky-500/5 p-5">
    <div className="flex items-start gap-3"><Box className="mt-1 text-emerald-400" size={24}/><div><h4 className="text-lg font-semibold">Сцена из записанного прохода</h4><p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">Оригинальные кадры → связанные камеры → визуальная сцена и отдельная модель поверхностей. Сохранённый результат можно вращать, изучать в каркасе и смотреть из ракурсов прохода. Обработка идёт на этом ПК, отдельно от Android.</p></div></div>
    {job?.creation&&!status&&!autoStopped.current&&<Button variant="outline" onClick={()=>{void stopWaiting();}}>Остановить ожидание</Button>}
    {(attempts.length>1||!job&&attempts.length>0)&&<label className="block max-w-lg text-sm">Сохранённые попытки реконструкции<select aria-label="Сохранённая попытка реконструкции" className="mt-1 block w-full rounded-lg border border-input bg-background p-2" value={job?.id??''} disabled={busy||!folder()} onChange={e=>{void selectAttempt(e.target.value);}}>{!job&&<option value="">Новое задание</option>}{attempts.map((item,index)=><option key={item.id} value={item.id}>Попытка {index+1} · {item.id.slice(0,8)}</option>)}</select><span className="mt-1 block text-xs text-muted-foreground">Выбор открывает сохранённый результат без повторной обработки.</span></label>}
    {!status&&<div className="flex flex-wrap items-end gap-4">
      <div className="w-full"><Button disabled={!complete||busy||!!job?.creation} onClick={()=>{void start(true);}}>Подготовить ориентиры</Button><p className="mt-2 text-xs text-muted-foreground">Одна обработка: исходное видео → камеры и точки → карта для живой проверки. Плотный 3D-рендер для движения не требуется.</p></div>
      <details className="w-full rounded-lg border p-3"><summary className="cursor-pointer text-xs">Дополнительные настройки и визуальная 3D-сцена</summary><div className="mt-3 flex flex-wrap items-end gap-4">
      <label className="text-sm">Маска записи<select className="mt-1 block rounded-lg border border-input bg-background p-2" value={mask} onChange={e=>setMask(e.target.value)}><option value="game">HUD и персонаж в центре</option><option value="avatar">Персонаж · HUD уже скрыт</option><option value="none">Без маски · свободный вид от первого лица</option></select></label>
      <label className="text-sm">Качество обработки<select className="mt-1 block rounded-lg border border-input bg-background p-2" value={steps} onChange={e=>setSteps(Number(e.target.value))}><option value={3000}>Проба · 3 000 шагов</option><option value={5000}>Стандарт · 5 000 шагов</option><option value={10000}>Детальнее · 10 000 шагов</option><option value={30000}>Высокая детализация · 30 000 шагов</option></select></label>
      {steps===30000&&<p className="max-w-lg text-sm text-muted-foreground">Более длительная обработка исходных кадров без уменьшения FullHD. Сохраняются промежуточные результаты; ограничения памяти и проверка качества действуют. Точность камер и полнота съёмки остаются важны.</p>}
      <Button variant="outline" disabled={!complete||uploading||recovering} onClick={()=>{void start(false);}}>Построить 3D-сцену</Button>
      <p className="w-full text-xs leading-5 text-muted-foreground">Подготовка ориентиров строит камеры и точки без долгого плотного рендера, затем автоматически проверяет карту. Точность пути и готовность управления проверяются отдельно.</p>
      </div></details>
    </div>}
    {status&&<div className="flex flex-wrap items-center gap-3"><p role="status" className="flex items-center gap-2 text-sm font-medium">{busy&&<Loader2 size={16} className="animate-spin"/>}{phases[status.phase]??status.phase}{uploading&&` · ${progress}`}{Number.isSafeInteger(status.completed_items)&&Number.isSafeInteger(status.total_items)&&(status.total_items??0)>0&&` · ${status.completed_items}/${status.total_items}`}</p>
      {busy&&!['pending_auto_prepare','preparing','features'].includes(status.navigation?.phase??'')&&<Button variant="outline" size="sm" onClick={()=>{void cancel();}}>Отменить обработку</Button>}
      {['pending_auto_prepare','preparing','features'].includes(status.navigation?.phase??'')&&<span className="text-xs text-muted-foreground">Подготовка ориентиров выполняется отдельно; её состояние обновляется автоматически.</span>}
      {status.phase==='uploading'&&!uploading&&<Button size="sm" onClick={()=>{void start();}}>Продолжить передачу</Button>}
      {['failed','cancelled'].includes(status.phase)?<Button variant="outline" size="sm" disabled={busy||!complete||!folder()} onClick={retryPreparation}>Повторить подготовку записи</Button>:terminalReconstruction(status)&&<Button variant="outline" size="sm" onClick={()=>{explicitNewAttempt.current=true;autoCandidate.current=null;sessionStorage.removeItem(storageKey);setJob(null);setStatus(null);setError(null);}}>Новое отдельное задание</Button>}
    </div>}
    <HudSpeedCard telemetry={status?.telemetry} sourceManifestSha={sourceManifestSha}/>
    {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    {preparationNotice&&preparationNotice.jobId===job?.id&&<p role="alert" className="text-sm text-destructive">{preparationNotice.message}</p>}
    {status?.error&&<p role="alert" className="text-sm text-destructive">{reasons[status.error]??status.error} Исходное видео не изменено.</p>}
    {status?.dense_partial_available&&status.checkpoint&&<p role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">Доступна проверенная промежуточная сцена: {status.checkpoint.steps} / {status.checkpoint.target_steps} итераций. Обработка не завершена успешно; это не окончательный результат.</p>}
    {status?.quality&&<p className="text-xs text-muted-foreground">Камеры {status.quality.registered}/{status.quality.selected} · покрытие {(status.quality.coverage*100).toFixed(0)}% · ошибка {status.quality.mean_reprojection_px.toFixed(2)} px</p>}
    {cameraMotionRequiresReview(status?.camera_motion)&&<p role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs leading-5 text-amber-500">Расчёт камер дал неоднозначный путь{status?.camera_motion?.rapid_reversals?`: ${status.camera_motion.rapid_reversals} подозрительных обратных скачка`:''}. Это диагностика восстановленных поз, а не утверждение о ваших движениях. Исходное видео сохранено. Движение по этой версии карты пока выключено.</p>}
    {job&&status?.geometry_available&&<div className="space-y-3 rounded-xl border border-sky-500/25 bg-sky-500/5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h5 className="font-medium">3D-модель поверхностей</h5><p className="mt-1 text-xs leading-5 text-muted-foreground">Треугольная сетка с фотографическими текстурами. Невидимые участки остаются пустыми; исходная сцена сохраняется отдельно.</p></div>
      <Button variant="outline" disabled={busy||!status.dense_available||!status.surface_supported||!terminalReconstruction(status)} onClick={()=>{void startSurface();}}>{models.length?'Построить другой фрагмент':'Построить поверхности'}</Button></div>
      <div className="flex flex-wrap items-end gap-4 text-xs"><label>Начальный ракурс<input disabled={busy} aria-label="Начальный ракурс фрагмента" className="mt-1 block w-28 rounded-md border bg-background p-2" type="number" min={1} max={Math.max(1,(status.quality?.registered??18)-2)} value={firstView+1} onChange={e=>setFirstView(Math.max(0,Math.min((status.quality?.registered??18)-3,Number(e.target.value)-1)))}/></label><label>Длина фрагмента<select disabled={busy} className="ml-2 rounded-md border bg-background p-2" value={viewCount} onChange={e=>setViewCount(Number(e.target.value))}><option value={12}>12 ракурсов</option><option value={18}>18 ракурсов</option><option value={24}>24 ракурса</option></select></label><p className="max-w-xl text-muted-foreground">Каждый участок сохраняется отдельно в этом маршруте. Повторно восстанавливать все камеры не требуется; модели не сшиваются автоматически.</p></div>
      {models.length>0&&<label className="block text-sm">Сохранённые участки<select aria-label="Сохранённый фрагмент маршрута" className="mt-2 block w-full rounded-lg border bg-background p-2" value={selectedModel?.id??'legacy'} onChange={e=>setSelectedFragment(e.target.value)}>{models.map((item,index)=><option key={item.id??'legacy'} value={item.id??'legacy'} disabled={!item.available}>Участок {index+1}{item.fragment?` · ракурсы ${item.fragment.first_view+1}–${item.fragment.first_view+item.fragment.view_count}`:''} · {surfaceLabels[item.phase]??item.phase}</option>)}</select></label>}
      {workingSurface&&<p role="status" className="text-sm">{surfaceLabels[workingSurface.phase]??workingSurface.phase}{workingSurface.total_views?` · ${workingSurface.views}/${workingSurface.total_views} ракурсов`:''}</p>}
      {selectedModel?.phase==='review_required'&&<p className="text-xs leading-5 text-amber-500">Осмотрите модель из нескольких ракурсов: ложные перемычки и разрывы возможны. Готовность файла не означает точную геометрию или допуск навигации.</p>}
      {selectedModel?.visual_review?.state==='issues_found'&&<p role="status" className="rounded-lg border border-amber-500/30 p-3 text-xs leading-5 text-amber-500">В проверенных ракурсах этого участка найдены дефекты: {selectedModel.visual_review.issues.map(issue=>({holes:'пропуски поверхностей',occluding_surfaces:'ложные перекрытия',stretched_triangles:'растянутые треугольники',pose_inconsistency:'сомнительное положение камер'})[issue]??issue).join(', ')}. Он доступен для диагностики и не считается качественной картой.</p>}
      {models.filter(item=>item.error).map(item=><p key={item.id??'legacy'} role="alert" className="text-sm text-destructive">{reasons[item.error!]??item.error}. Исходные материалы и предыдущая сцена сохранены.</p>)}
      {selectedModel?.result&&<p className="text-xs text-muted-foreground">{selectedModel.result.triangles.toLocaleString('ru')} треугольников · {selectedModel.result.textures} фотографий · {(selectedModel.result.bytes/1048576).toFixed(1)} МБ · исключено без видимого покрытия: {selectedModel.result.unknown_faces.toLocaleString('ru')} граней</p>}
      {!status.surface_supported&&!status.surface&&<p className="text-xs text-muted-foreground">Локальный инструмент OpenMVS CPU ещё не подготовлен.</p>}
    </div>}
    {visible&&job&&status?.dense_available&&<ReferenceComparison job={job} appearance={status.appearance}/>}
    {job&&status?.geometry_available&&<div className="space-y-3 rounded-xl border border-cyan-500/25 bg-cyan-500/5 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h5 className="font-medium">Карта ориентиров для живой проверки</h5><p className="mt-1 text-xs leading-5 text-muted-foreground">Сохранённые камеры и реальные 3D-опоры → определение положения по свежему кадру. Воспроизведение нажатий не используется.</p></div><Button variant="outline" disabled={busy||!(status.dense_available||status.sparse_available)||cameraMotionRequiresReview(status.camera_motion)||status.navigation?.error==='route_camera_motion_requires_review'||status.navigation?.error==='route_preparation_attempt_quota'||status.navigation?.error==='route_map_has_unobserved_sections'||quotaJob===job.id||status.navigation?.phase==='ready'} onClick={()=>{void prepareRoute();}}>{status.navigation?.phase==='ready'?'Карта подготовлена':'Подготовить маршрут'}</Button></div><p role="status" className="text-xs">{status.navigation?.phase==='ready'?`Готово для ручной проверки · ${status.navigation.summary?.cameras??'—'} камер · ${status.navigation.summary?.landmarks??'—'} ориентиров`:!(status.dense_available||status.sparse_available)?'Камеры или обработка сцены не прошли проверку; ориентиры пока не подготовить.':cameraMotionRequiresReview(status.camera_motion)?'Траектория камер требует проверки; повторная подготовка не исправит её.':navigationPhaseLabel(status.navigation?.phase)}{status.navigation?.error?` · ${navigationErrorLabel(status.navigation.error)}`:''}</p>{routeCoverageLabel(status.navigation?.summary)&&<p className="text-xs text-muted-foreground">{routeCoverageLabel(status.navigation?.summary)}</p>}<p className="text-xs leading-5 text-muted-foreground">После подготовки откройте режим «Направление» наверху страницы. Это ещё не допуск автономной поездки: поверхность дороги, препятствия и моторная модель проверяются отдельно.</p></div>}
    {alternativeCameraCount!==null&&<p className="rounded-lg border border-cyan-500/25 bg-cyan-500/5 p-3 text-xs leading-5">Схема на {alternativeCameraCount} камер открыта выше. Ниже — 3D-представление основной попытки ({status?.quality?.registered??'—'} камер). Живое положение привязывается к основной карте.</p>}
    {scene}
    <p className="text-xs text-muted-foreground">Ссылка на результат сохранена рядом с записью в библиотеке этого браузера и аккаунта. Выберите этот проход снова, чтобы открыть готовую сцену. Сохранённая сцена остаётся на локальном ПК.</p>
    <p className="text-xs leading-5 text-muted-foreground">Маска применяется до поиска признаков; она не распознаёт все движущиеся машины и игроков. Плотная сцена — визуальная реконструкция, а не готовая карта коллизий. Масштаб в метрах требует отдельного известного расстояния. При нехватке связных ракурсов обработка остановится с объяснением.</p>
  </section>;
}
