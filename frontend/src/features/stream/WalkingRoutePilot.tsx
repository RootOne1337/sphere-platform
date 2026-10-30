'use client';
import {useEffect,useRef,useState,type RefObject,type ReactNode} from 'react';
import {Footprints,Square,Download} from 'lucide-react';
import {Button} from '@/components/ui/button';
import Image from 'next/image';
import {reconstructionRequest,type ReconstructionJob} from './reconstructionClient';
import {freshNavigationFrame,navigationReply,type LiveRouteObservation} from './routeNavigation';
import {WalkLivePreview,type WalkPreviewFrame} from './WalkLivePreview';
import {readWalkPlan,walkReasonLabel,waitForFreshWalkSource,type WalkInputControl,type WalkInputLease} from './walkPilot';
import type {TeachingInput} from './teachingContacts';
import {saveRouteDebugReport} from './routeDebugStorage';
import {RouteDebugArchive} from './RouteDebugArchive';
import {WalkRunDiagnostics,walkInputSummary,walkCameraInputSummary} from './walkRunDiagnostics';
import {WalkCameraDrag as WalkCameraServo,type CameraDragStep as CameraStep} from './walkCameraDrag';

type Binding={captureEpoch:string;width:number;height:number};
type StartMode='beginning'|'recognized_route';
type Sample={elapsedMs:number;sequence:number;ageMs:number;computeMs:number;state:string;reason:string;
  poseState:'unknown'|'confirming'|'localized';
  inliers:number;progress:number|null;stick:[number,number];jpegSha256:string;image?:string;
  poseReason:string;plannerReason:string;cameraYawRadians:number|null;segment:number|null;medianErrorPx:number|null;crossTrackUnits:number|null;center:number[]|null;rotation:number[]|null;geometrySha256:string|null};
type Run={id:string;job:ReconstructionJob;abort:AbortController;lease:WalkInputLease|null;opening:Promise<WalkInputLease>|null;began:number;
  binding:Binding;deadline:number;permitUntil:number;moving:boolean;lastSequence:number;clip:string|null;scope:string|null;
  freshUntil:number|null;freshWaits:number;trace:WalkRunDiagnostics;
  observe:(()=>void)|null;inFlight:boolean;nextObservationAt:number;startMode:StartMode;camera:WalkCameraServo|null;binaryJpeg?:boolean;lastPreviewAt?:number};

/** Explicit supervised foot experiment; the observer above remains read-only. */
export function WalkingRoutePilot({job,clip,video,ready,binding,assetsReady,input,observerBusy,onBusyChange,onObservation,renderView,scope=null,preparationIssue=null}:{
  job:ReconstructionJob|null;clip:string|null;video:RefObject<HTMLVideoElement|null>;ready:boolean;
  binding:Binding|null;assetsReady:boolean;input:WalkInputControl;observerBusy:boolean;onBusyChange:(busy:boolean)=>void;
  onObservation?:(observation:LiveRouteObservation|null)=>void;renderView?:(view:ReactNode)=>ReactNode;
  scope?:string|null;preparationIssue?:string|null;
}) {
  const [confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[saveFrames,setSaveFrames]=useState(true);
  const [startMode,setStartMode]=useState<StartMode>('recognized_route');
  const [cameraEnabled,setCameraEnabled]=useState(input.cameraIssue!==undefined);
  const [notice,setNotice]=useState('Пеший тест запускается отдельно. Записанные клавиши не воспроизводятся.');
  const [release,setRelease]=useState<'none'|'pending'|'closed'|'unknown'>('none');
  const [samples,setSamples]=useState<Sample[]>([]),[events,setEvents]=useState(0);
  const [savedDebug,setSavedDebug]=useState('Диагностика сохранится локально после освобождения ввода.');
  const [stopDetail,setStopDetail]=useState<string|null>(null);
  const [previewFrame,setPreviewFrame]=useState<WalkPreviewFrame|null>(null);
  const history=useRef<Sample[]>([]),inputs=useRef<TeachingInput[]>([]),images=useRef(0),lastImageAt=useRef(-Infinity);
  const output=useRef<HTMLCanvasElement>(null),run=useRef<Run|null>(null),retired=useRef<Promise<void>|null>(null);
  const current=useRef({ready,binding});current.current={ready,binding};
  const recent=useRef({sequence:0,at:0}),stopRef=useRef<(reason:string)=>Promise<void>>(async()=>{});
  const lastSource=useRef<HTMLCanvasElement|null>(null);
  const lastReport=useRef<Record<string,unknown>|null>(null),lastEventPaint=useRef(-Infinity);
  const lastUiPaint=useRef(-Infinity);
  const busyChange=useRef(onBusyChange);busyChange.current=onBusyChange;
  const observed=useRef(onObservation);observed.current=onObservation;
  const captureEpoch=binding?.captureEpoch;
  const cameraCommand=(active:Run,step:CameraStep,sequence:number,notAfter:number)=>{
    if(!step.action||!active.camera||!active.lease?.drag)return;
    const camera=active.camera,lease=active.lease;
    if(step.action!=='up'&&performance.now()>=notAfter){camera.cancelUnsentStroke();return;}
    active.trace.add('camera_command',performance.now(),{sequence,reason:step.reason});
    void lease.drag!(step.action==='up'?null:step.fraction,notAfter).then(applied=>{
      if(run.current!==active||active.abort.signal.aborted)return;
      camera.finishStroke(applied,performance.now());
      active.trace.add('camera_result',performance.now(),{sequence,reason:applied?'applied':'unconfirmed'});
      if(!applied)void stopRef.current(lease.failure?.()??'walk_camera_input_unconfirmed');
    }).catch(()=>{if(run.current===active)void stopRef.current('walk_camera_input_unconfirmed');});
  };
  const clear=()=>{
    const draw=output.current?.getContext('2d');if(!draw)return;
    // Keep the source image for diagnosis, without reusing a route overlay or
    // presenting a stopped session as live. The visible badge marks this frame.
    const source=lastSource.current??video.current;
    try{if(source)draw.drawImage(source,0,0,960,540);}catch{draw.clearRect(0,0,960,540);}
  };
  const neutralUntilFresh=(active:Run,reason='permit_expired')=>{
    if(!active.lease?.active())return false;
    if(active.freshUntil===null){active.freshWaits++;active.freshUntil=performance.now()+2000;
      active.trace.add('neutral_wait',performance.now(),{reason,sequence:active.lastSequence});}
    active.lease.set([0,0]);active.moving=false;
    if(active.camera&&active.lease.canLook?.())cameraCommand(active,active.camera.pause(performance.now()),active.lastSequence,performance.now()+200);
    // A late delivery is not loss of geometric localization. The server still
    // requires three poses after an actual loss. Resume only on a NEW, fresh,
    // bound localized/following reply, never on the expired command.
    setNotice('Стик в центре: ждём новое свежее решение, до 2 секунд. Повторного нажатия нет.');
    return true;
  };
  const stop=async(reason:string)=>{
    const active=run.current;
    if(!active)return retired.current??Promise.resolve();
    const frameSequence=recent.current.sequence,frameAge=frameSequence?Math.max(0,performance.now()-recent.current.at):null;
    const inputFailure=active.lease?.failure?.()??null;
    if(inputFailure)reason=inputFailure;
    active.trace.add('stop',performance.now(),{reason,sequence:frameSequence,...(frameAge===null?{}:{ageMs:frameAge})});
    setStopDetail(`Кадров источника: ${frameSequence}; возраст: ${frameAge===null?'нет кадра':`${frameAge.toFixed(0)} мс`}; ответов локализации: ${history.current.length}.`);
    run.current=null;active.abort.abort();observed.current?.(null);setNotice(walkReasonLabel(reason));setRelease('pending');
    const closing=(async()=>{
      let released=true,lease=active.lease;
      try{if(!lease&&active.opening)lease=await active.opening;if(lease)released=await lease.close();}
      catch{released=false;}
      clear(); // Optional canvas work follows native closure, never precedes it.
      try{await reconstructionRequest(`/jobs/${active.job.id}/navigation/stop`,active.job,{method:'POST',body:JSON.stringify({id:active.id})});}catch{/* Same intent is fenced by its deadline; never retry a start. */}
      setRelease(released?'closed':'unknown');setBusy(false);busyChange.current(false);
      setEvents(inputs.current.length);
      if(!released)setNotice('Освобождение ввода НЕ подтверждено. Новый запуск заблокирован; переподключите поток.');
      const report={schema:'sphere-walk-debug-v1',scope:'supervised_camera_trace_pilot',clip:active.clip,job:active.job.id,
          executionQualified:false,metricAccuracyKnown:false,sourceCaptureAgeKnown:false,release:released?'closed':'unknown',stopReason:reason,
          stopFrameAgeMs:frameAge,stopFrameSequence:frameSequence,inputFailure,startMode:active.startMode,camera:active.camera?.snapshot()??null,cameraInput:walkCameraInputSummary(inputs.current),stages:active.trace.snapshot(),
          observations:history.current.map(row=>({...row,center:row.center?[...row.center]:null,rotation:row.rotation?[...row.rotation]:null})),nativeInputs:inputs.current.map(row=>({...row})),nativeInputTailLimit:4096};
      lastReport.current=report;
      if(active.scope&&active.clip){
        setSavedDebug('Сохраняем диагностику завершённого теста…');
        void(async()=>{
          const [archive,local]=await Promise.allSettled([
            saveRouteDebugReport(active.scope!,active.clip!,active.id,report),
            reconstructionRequest(`/jobs/${active.job.id}/navigation/walk-report`,active.job,{method:'POST',body:JSON.stringify({
              schema:'sphere-walk-summary-v1',id:active.id,clip:active.clip,release:report.release,stopReason:reason,inputFailure,startMode:active.startMode,
              stopFrameAgeMs:frameAge,stopFrameSequence:frameSequence,executionQualified:false,camera:report.camera,cameraInput:report.cameraInput,
              inputSummary:{...walkInputSummary(inputs.current),events:inputs.current.length},stages:report.stages,
              observations:report.observations.map(({elapsedMs,sequence,ageMs,computeMs,state,reason,poseState,inliers,progress,segment,medianErrorPx,crossTrackUnits,poseReason,plannerReason,cameraYawRadians})=>({elapsedMs,sequence,ageMs,computeMs,state,reason,poseState,inliers,progress,segment,medianErrorPx,crossTrackUnits,poseReason,plannerReason,cameraYawRadians})),
            })}).then(response=>response.json()).then(value=>{if(!['saved','existing'].includes(value.state)||value.physicalActions!==0)throw Error('walk_report_unconfirmed');}),
          ]);
          const saved=archive.status==='fulfilled'&&['saved','existing'].includes(archive.value.state);
          setSavedDebug(`${saved?'Архив браузера сохранён.':'Архив браузера не подтверждён; скачайте отчёт.'} ${local.status==='fulfilled'?'Сводка без кадров сохранена локальным обработчиком.':'Сводка обработчика не подтверждена; автоматического повтора нет.'}`);
        })();
      }
    })();
    retired.current=closing;await closing;
  };
  stopRef.current=stop;
  useEffect(()=>()=>{void stopRef.current('walk_stream_changed');},[]);
  useEffect(()=>{setConfirmed(false);void stopRef.current('walk_stream_changed');},[job?.id,job?.key,clip,binding?.captureEpoch,binding?.width,binding?.height]);
  useEffect(()=>{if(binding?.captureEpoch)setRelease('none');},[binding?.captureEpoch]);
  useEffect(()=>{
    recent.current={sequence:0,at:0};lastSource.current=null;setPreviewFrame(null);const element=video.current;
    if(!captureEpoch||!element?.requestVideoFrameCallback)return;
    let closed=false,id=0;
    const next=()=>{id=element.requestVideoFrameCallback(()=>{
      if(closed)return;
      const now=performance.now(),previous=recent.current;
      if(previous.sequence&&now-previous.at>100)run.current?.trace.add('source_gap',now,{durationMs:now-previous.at,sequence:previous.sequence});
      recent.current={sequence:previous.sequence+1,at:now};
      if(!run.current||!history.current.length){try{output.current?.getContext('2d')?.drawImage(element,0,0,960,540);}catch{/* No control authority comes from a failed preview draw. */}}
      run.current?.observe?.();
      next();
    });};
    next();return()=>{closed=true;element.cancelVideoFrameCallback(id);};
  },[video,captureEpoch]);
  useEffect(()=>{
    if(typeof PerformanceObserver==='undefined'||!PerformanceObserver.supportedEntryTypes?.includes('longtask'))return;
    const observer=new PerformanceObserver(list=>{const active=run.current;if(!active)return;
      for(const entry of list.getEntries())active.trace.add('long_task',entry.startTime+entry.duration,{durationMs:entry.duration});});
    observer.observe({type:'longtask'});return()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    const timer=setInterval(()=>{
      const active=run.current;if(!active)return;
      const now=performance.now(),source=current.current;
      if(source.binding?.captureEpoch!==active.binding.captureEpoch)void stopRef.current('walk_stream_changed');
      else if(!freshNavigationFrame(recent.current.at,now)){
        if(!active.lease&&!active.moving&&now-recent.current.at<1000)return;
        // A moving/uncertain native contact still closes immediately in
        // TeachingContacts. Only an empty owner can wait for new video.
        try{if(active.moving||now-recent.current.at>=1000||!neutralUntilFresh(active,'source_gap'))void stopRef.current('walk_stream_changed');}
        catch{void stopRef.current(active.lease?.failure?.()??'walk_native_closed');}
      }
      else if(now>=active.deadline)void stopRef.current('walk_time_limit');
      else if(active.freshUntil!==null&&now>=active.freshUntil)void stopRef.current('walk_decision_expired');
      else if(active.moving&&now>active.permitUntil){try{if(!neutralUntilFresh(active))void stopRef.current('walk_decision_expired');}catch{void stopRef.current('walk_native_closed');}}
      else if(active.lease&&!active.lease.active())void stopRef.current(active.lease.failure?.()??'walk_native_closed');
    },25);
    const hidden=()=>{if(document.hidden)void stopRef.current('walk_manual_stop');};
    const blur=()=>{void stopRef.current('walk_manual_stop');};
    const escape=(event:KeyboardEvent)=>{if(event.code==='Escape'){event.preventDefault();void stopRef.current('walk_manual_stop');}};
    document.addEventListener('visibilitychange',hidden);window.addEventListener('blur',blur);window.addEventListener('keydown',escape);
    return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',hidden);window.removeEventListener('blur',blur);window.removeEventListener('keydown',escape);};
  },[]);
  const start=async()=>{
    if(!job||!binding||!ready||!assetsReady||!confirmed||input.issue||cameraEnabled&&input.cameraIssue||observerBusy||busy||run.current||release==='unknown')return;
    if(!freshNavigationFrame(recent.current.at,performance.now())){setNotice('Дождитесь свежего кадра прямого потока.');return;}
    const began=performance.now();
    const active:Run={id:crypto.randomUUID().replaceAll('-',''),job,abort:new AbortController(),lease:null,opening:null,began,
      binding:{...binding},deadline:began+60000,permitUntil:0,moving:false,lastSequence:0,clip,scope,freshUntil:null,freshWaits:0,trace:new WalkRunDiagnostics(began),observe:null,inFlight:false,nextObservationAt:0,startMode,camera:cameraEnabled?new WalkCameraServo():null};
    run.current=active;setBusy(true);busyChange.current(true);setRelease('none');setStopDetail(null);clear();setNotice('Открываем отдельный пеший тест. До узнавания старта стик нейтрален.');
    history.current=[];inputs.current=[];images.current=0;lastImageAt.current=-Infinity;lastReport.current=null;lastUiPaint.current=-Infinity;setSamples([]);setEvents(0);
    const signal=active.abort.signal,alive=()=>run.current===active&&!signal.aborted;
    try{
      const state=await(await reconstructionRequest(`/jobs/${job.id}/navigation/walk-start`,job,{method:'POST',signal,
        body:JSON.stringify({id:active.id,captureEpoch:binding.captureEpoch,width:binding.width,height:binding.height,sceneConfirmed:true,footCameraAssumptionConfirmed:true,startMode:active.startMode,cameraTracking:!!active.camera,...(active.camera?{cameraControl:'continuous_drag_v1'}:{})})})).json();
      if(!alive())return;
      if(state.id!==active.id||state.phase!=='observing'||state.mode!=='foot_camera_trace_v1'||state.physicalActions!==0||state.maxSeconds!==60||state.startMode!==active.startMode)throw Error('walk_start_unconfirmed');
      if(active.camera?state.cameraTracking!==true:state.cameraTracking===true)throw Error('walk_start_unconfirmed');
      if(active.camera&&state.cameraControl!=='continuous_drag_v1')throw Error('walk_start_unconfirmed');
      active.binaryJpeg=state.observationProtocol==='jpeg_binary_v1';
      if(!freshNavigationFrame(recent.current.at,performance.now()))setNotice('Ждём свежий кадр перед открытием ввода. Касаний ещё нет.');
      if(!await waitForFreshWalkSource(()=>freshNavigationFrame(recent.current.at,performance.now()),signal))throw Error('walk_source_not_ready');
      if(!alive())return;
      active.trace.add('input_open',performance.now());
      active.opening=input.open(signal,event=>{if(inputs.current.length>=4096)inputs.current.shift();inputs.current.push(event);
        if(performance.now()-lastEventPaint.current>=200){lastEventPaint.current=performance.now();setEvents(inputs.current.length);}});
      const lease=await active.opening;
      active.lease=lease;
      if(!alive()){await lease.close();return;}
      if(!lease.active())throw Error(lease.failure?.()??'walk_native_closed');
      if(active.camera&&(!lease.drag||!lease.canLook))throw Error('walk_camera_input_unconfirmed');
      if(active.camera&&lease.cameraLimits)active.camera.setBounds(lease.cameraLimits);
      active.trace.add('input_ready',performance.now());
      const canvas=document.createElement('canvas');canvas.width=960;canvas.height=540;
      const context=canvas.getContext('2d',{willReadFrequently:true});if(!context)throw Error('walk_canvas_unavailable');
      const observe=async()=>{
        if(!alive()||active.inFlight||performance.now()<active.nextObservationAt)return;
        const began=performance.now(),frame=recent.current;
        // Start alongside presentation, not an unrelated 100 ms polling phase
        // that can select a frame already 80 ms old before JPEG/HTTP even begin.
        if(frame.sequence===active.lastSequence||!freshNavigationFrame(frame.at,began)||began-frame.at>34)return;
        active.inFlight=true;active.nextObservationAt=began+50;
        try{
          active.lastSequence=frame.sequence;context.drawImage(video.current!,0,0,960,540);
          lastSource.current=canvas;
          const blob=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(v=>v?resolve(v):reject(Error('walk_jpeg_unavailable')),'image/jpeg',.92));
          if(blob.size>384*1024)throw Error('walk_jpeg_quota');
          const bytes=await blob.arrayBuffer(),sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
          // New services receive the original JPEG bytes directly. Legacy
          // JSON/base64 remains negotiated only for an older local service.
          const jpeg=active.binaryJpeg?null:await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('walk_jpeg_unavailable'));reader.readAsDataURL(blob);});
          active.trace.add('jpeg',performance.now(),{sequence:frame.sequence,durationMs:performance.now()-began,ageMs:performance.now()-frame.at});
          if(!alive())return;
          if(!freshNavigationFrame(frame.at,performance.now()))throw Error('walk_decision_expired');
          const sentAt=performance.now();
          const value=await(await reconstructionRequest(`/jobs/${job.id}/navigation/${active.binaryJpeg?'observe-jpeg':'observe'}`,job,active.binaryJpeg?
            {method:'POST',signal,headers:{'Content-Type':'image/jpeg','X-Route-Session':active.id,'X-Capture-Epoch':binding.captureEpoch,'X-Frame-Sequence':String(frame.sequence)},body:blob}:
            {method:'POST',signal,body:JSON.stringify({id:active.id,captureEpoch:binding.captureEpoch,sequence:frame.sequence,jpeg})})).json();
          if(!alive())return;
          active.trace.add('http',performance.now(),{sequence:frame.sequence,durationMs:performance.now()-sentAt,ageMs:performance.now()-frame.at});
          const reply=navigationReply(value,active.id,binding.captureEpoch,frame.sequence,sha),plan=readWalkPlan(value.walk),now=performance.now();
          if(!reply||!plan)throw Error('walk_reply_not_bound');
          if(!lease.active())throw Error(lease.failure?.()??'walk_native_closed');
          if(!freshNavigationFrame(frame.at,now))throw Error('walk_decision_expired');
          let command=plan.stick;
          if(active.freshUntil!==null){
            // Fresh delivery and geometric localization are separate states.
            // A fresh UNKNOWN still resolves the transport wait; the server's
            // neutral pose plan does not acquire movement authority.
            active.freshUntil=null;
          }
          if(plan.phase==='following'&&reply.pose.state!=='localized')throw Error('walk_reply_pose_mismatch');
          let cameraStep:CameraStep|null=null;
          if(active.camera&&reply.pose.state==='localized'&&plan.phase==='following'){
            cameraStep=active.camera.update({rotation:reply.pose.rotation??[],target:value.walk?.targetCamera,
              sequence:frame.sequence,capturedAt:frame.at,now,canStroke:lease.canLook?.()===true,
              alignmentRequired:plan.reason==='walk_camera_alignment_required'});
            if(cameraStep.failed)throw Error(cameraStep.reason);
            if(cameraStep.hold)command=[0,0];
          }else if(active.camera&&lease.canLook?.())cameraStep=active.camera.pause(now);
          const sample:Sample={elapsedMs:now-active.began,sequence:frame.sequence,ageMs:now-frame.at,computeMs:reply.computeMs,
            state:plan.phase,reason:plan.phase==='stopped'||plan.phase==='arrived'?plan.reason:(cameraStep?.reason??plan.reason),
            poseState:reply.pose.state,inliers:reply.pose.inliers,progress:plan.progressFraction,stick:command,jpegSha256:sha,
            poseReason:reply.pose.reason,plannerReason:plan.reason,cameraYawRadians:cameraStep?.yaw??null,segment:reply.pose.segment,medianErrorPx:reply.pose.median_error_px??null,
            crossTrackUnits:reply.pose.cross_track_units??null,center:reply.pose.center?[...reply.pose.center]:null,rotation:reply.pose.rotation?[...reply.pose.rotation]:null,geometrySha256:reply.geometrySha256??null};
          // Deliver the fresh decision before any diagnostic canvas or React
          // work. Rendering may be skipped; input identity/deadline never is.
          active.permitUntil=frame.at+250;
          if(plan.phase==='stopped'||plan.phase==='arrived'){if(history.current.length<1200)history.current.push(sample);await stop(plan.reason);return;}
          if(performance.now()>active.permitUntil){
            if(cameraStep?.action)active.camera?.cancelUnsentStroke();
            if(!neutralUntilFresh(active,'render_expired'))await stop('walk_decision_expired');
            return;
          }
          active.moving=plan.phase==='following'&&Math.hypot(...command)>0;
          lease.set(command);
          active.trace.add('input_command',performance.now(),{sequence:frame.sequence,ageMs:performance.now()-frame.at});
          if(cameraStep?.action)cameraCommand(active,cameraStep,frame.sequence,active.permitUntil);
          if(history.current.length<1200)history.current.push(sample);
          const paintUi=now-lastUiPaint.current>=200;
          if(paintUi){lastUiPaint.current=now;observed.current?.({reply,capturedAt:frame.at,answeredAt:now});}
          const keep=saveFrames&&images.current<60&&now-lastImageAt.current>=1000;
          let diagnosticJpeg=jpeg;
          if(keep&&!diagnosticJpeg)diagnosticJpeg=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('walk_jpeg_unavailable'));reader.readAsDataURL(blob);});
          if(!alive())return;
          if(keep){images.current++;lastImageAt.current=now;}
          if(keep)sample.image=`data:image/jpeg;base64,${diagnosticJpeg}`;
          if(paintUi)setSamples([...history.current.slice(-8)]);
          if(now-(active.lastPreviewAt??-Infinity)>=100){active.lastPreviewAt=now;
            setPreviewFrame({blob,sequence:frame.sequence,capturedAt:frame.at,points:reply.pose.state==='localized'?reply.pose.polyline_px:[]});}
          if(paintUi)setNotice(walkReasonLabel(sample.reason));
        }catch(error){if(alive()){
          if(error instanceof Error&&error.message==='walk_decision_expired'){
            active.trace.add('decision_expired',performance.now(),{sequence:frame.sequence,ageMs:performance.now()-frame.at});
            try{if(neutralUntilFresh(active,'reply_expired'))return;}catch{/* A closed native owner is terminal. */}
          }
          await stop(error instanceof Error?error.message:'walk_request_failed');
        }}
        finally{
          active.inFlight=false;
          // One in-flight request and no queue. If a newer frame arrived during
          // computation it may be used only while still fresh at this instant.
          if(alive()&&recent.current.sequence!==active.lastSequence)queueMicrotask(()=>{void observe();});
        }
      };
      active.observe=()=>{void observe();};
      void observe();
    }catch(error){if(alive())await stop(error instanceof Error?error.message:'walk_start_unconfirmed');}
  };
  const download=()=>{
    const report=lastReport.current??{schema:'sphere-walk-debug-v1',scope:'supervised_camera_trace_pilot',clip,job:job?.id,
      executionQualified:false,metricAccuracyKnown:false,sourceCaptureAgeKnown:false,release,
      observations:history.current,nativeInputs:inputs.current,nativeInputTailLimit:4096};
    const url=URL.createObjectURL(new Blob([JSON.stringify(report)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='sphere-walk-debug.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const last=samples.at(-1);
  const inputProgress=walkInputSummary(inputs.current);
  const cameraProgress=walkCameraInputSummary(inputs.current);
  const cameraFeedback=(run.current?.camera?.snapshot()??lastReport.current?.camera as ReturnType<WalkCameraServo['snapshot']>|null)?.feedback?.at(-1);
  return <section aria-label="Пеший тест маршрута" className="space-y-3 rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4">
    <div className="flex items-center gap-2"><Footprints size={19} className="text-amber-500"/><h3 className="font-semibold">Пеший тест · живой стик</h3><span className="ml-auto text-xs text-muted-foreground">до 60 с · до 35% стика</span></div>
    <p className="text-xs leading-5 text-muted-foreground">По свежим ориентирам выбираем ближайшую цель на записанном пути камеры. При краткой потере позиции стик возвращается в центр с удержанием пальца: до 2 секунд ждём три подтверждения рядом с последней позицией, максимум три раза за тест. Устаревший кадр, разрыв потока, скачок или отсутствие прогресса останавливают тест. Объезд препятствий не реализован, точность в метрах ещё не измерена.</p>
    <label className="flex flex-wrap items-center gap-2 text-xs">Начало движения<select aria-label="Точка запуска пешего теста" className="rounded-lg border bg-background p-2" value={startMode} disabled={busy} onChange={e=>{setStartMode(e.target.value as StartMode);setConfirmed(false);}}><option value="recognized_route">С текущей узнанной точки маршрута</option><option value="beginning">Только у начала записи</option></select></label>
    <p className="text-xs text-muted-foreground">После обрыва можно снова нажать запуск на записанном участке. Положение определяется заново по живым кадрам; цель выбирается дальше по записи. При неоднозначном месте движение не начинается.</p>
    <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={cameraEnabled} disabled={busy} onChange={e=>{setCameraEnabled(e.target.checked);setConfirmed(false);}}/>Поворачивать камеру вдоль пути · горизонтально, с проверкой по новым кадрам</label>
    <p className="text-xs text-muted-foreground">Перед поворотом стик возвращается в центр без нового нажатия. Палец камеры удерживается; каждое движение корректируется по новому кадру. Знак и чувствительность определяются по отклику. Вертикальных свайпов нет; при сильном наклоне восстановите ракурс вручную. Режим пока требует живой проверки.</p>
    {cameraEnabled&&input.cameraIssue&&<p className="text-xs text-amber-500">{input.cameraIssue}</p>}
    <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}/>Персонаж пешком на записанном участке, ракурс и FOV соответствуют записи, путь свободен; готов остановить тест</label>
    <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={saveFrames} disabled={busy} onChange={e=>setSaveFrames(e.target.checked)}/>Диагностика: до 60 кадров, положения стика и подтверждения Android остаются в этой вкладке</label>
    {(input.issue||!assetsReady)&&<p className="text-xs text-amber-500">{!assetsReady?(preparationIssue??'Проверяем обработку записи и готовность ориентиров…'):input.issue}</p>}
    <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy||observerBusy||!job||!ready||!assetsReady||!confirmed||!!input.issue||cameraEnabled&&!!input.cameraIssue||release==='unknown'} onClick={()=>{void start();}}>Запустить пеший тест · 60 с</Button><Button size="sm" variant="destructive" disabled={!busy} onClick={()=>{void stop('walk_manual_stop');}}><Square size={13} className="mr-1"/>Стоп пешего теста · Esc</Button><Button size="sm" variant="outline" disabled={!samples.length||busy} onClick={download}><Download size={13} className="mr-1"/>Скачать отчёт теста</Button></div>
    <p role="status" className="rounded-lg border bg-background/60 p-3 text-xs">{notice}</p>
    {stopDetail&&<p className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-3 text-xs">{stopDetail}</p>}
    <div aria-label="Подтверждение движения" className="grid gap-2 text-xs sm:grid-cols-3">
      <p className="rounded-lg border p-3">Ориентиры: <strong>{last?`${last.inliers} совпадений`:'ожидаются'}</strong></p>
      <p className="rounded-lg border p-3">Команды стику: <strong>{inputProgress.submitted}</strong></p>
      <p className="rounded-lg border p-3">Android применил: <strong>{inputProgress.applied}</strong></p>
    </div>
    {cameraEnabled&&<p aria-label="Подтверждение камеры" className="rounded-lg border p-3 text-xs">Камера: Android подтвердил <strong>{cameraProgress.strokesApplied} / {cameraProgress.strokesSubmitted}</strong> жестов · MOVE подтверждены: {cameraProgress.movesApplied}{cameraProgress.lastDistancePx!==null&&` · последний ${cameraProgress.lastDistancePx} px / ${cameraProgress.lastDurationMs?.toFixed(0)} мс`}. Подтверждение касания и изменение ракурса проверяются отдельно.</p>}
    {cameraEnabled&&cameraFeedback&&<p className="text-xs text-muted-foreground">Отклик по ориентирам: {(cameraFeedback.turnRadians*180/Math.PI).toFixed(2)}° · угол до пути: {(cameraFeedback.yawAfter*180/Math.PI).toFixed(1)}°.</p>}
    {!busy&&history.current.some(row=>row.poseState==='localized')&&inputProgress.submitted===0&&<p className="text-xs text-amber-500">Место узнано, но команда движения не выдавалась. Это не ошибка подтверждения Android; причина остановки указана выше.</p>}
    {!busy&&inputProgress.submitted>0&&inputProgress.applied===0&&<p className="text-xs text-amber-500">Команда стику отправлена, но Android ещё не подтвердил касание. Этот запуск не подтвердил движение по маршруту.</p>}
    <p className="text-[11px] text-muted-foreground">{savedDebug}</p>
    {scope&&clip&&<RouteDebugArchive scope={scope} clip={clip} refresh={savedDebug}/>}
    <div className="grid grid-cols-3 gap-2 text-xs tabular-nums"><div>Прогресс: {last?.progress==null?'—':`${(last.progress*100).toFixed(1)}%`}</div><div>Опоры: {last?.inliers??0}</div><div>Кадр → ответ: {last?`${last.ageMs.toFixed(0)} мс`:'—'}</div><div>Стик: {release==='unknown'?'UNKNOWN':busy&&last?last.stick.map(v=>v.toFixed(2)).join(' / '):'0 / 0'}</div><div>События ввода: {events}</div><div>Освобождение: {({none:'—',pending:'ожидается',closed:'CLOSED',unknown:'UNKNOWN'})[release]}</div></div>
    {(()=>{const preview=<figure className="space-y-2"><figcaption className="text-xs text-muted-foreground">{busy?'Пеший тест: исходный кадр и подтверждённое направление':'Просмотр источника · автоматическое движение выключено'}</figcaption><canvas ref={output} width={960} height={540} aria-label="Диагностика пешего теста на свежем кадре" className={previewFrame?'hidden':'aspect-video w-full rounded-lg border bg-black'}/>{previewFrame&&<WalkLivePreview frame={previewFrame} active={busy}/>}</figure>;return renderView?renderView(preview):preview;})()}
    {!busy&&samples.length>0&&<details><summary className="cursor-pointer text-xs">Кадры диагностики · {images.current}</summary><div className="mt-2 grid grid-cols-2 gap-2">{history.current.filter(s=>s.image).map(s=><figure key={s.sequence}><Image src={s.image!} width={960} height={540} unoptimized alt={`Кадр теста ${(s.elapsedMs/1000).toFixed(1)} с`} className="w-full rounded border"/><figcaption className="text-[10px]">{(s.elapsedMs/1000).toFixed(1)} с · {s.inliers} опор · {s.progress==null?'позиция неизвестна':`${(s.progress*100).toFixed(1)}%`}</figcaption></figure>)}</div></details>}
    {!!samples.length&&<div className="overflow-auto"><table className="w-full text-left text-[11px] tabular-nums"><caption className="pb-2 text-left text-muted-foreground">Последние наблюдения · относительный прогресс, без метров</caption><thead><tr><th>Время</th><th>Опоры</th><th>Стик X/Y</th><th>Состояние</th></tr></thead><tbody>{samples.map(s=><tr key={s.sequence}><td>{(s.elapsedMs/1000).toFixed(1)} с</td><td>{s.inliers}</td><td>{s.stick.map(n=>n.toFixed(2)).join(' / ')}</td><td>{walkReasonLabel(s.reason)}</td></tr>)}</tbody></table></div>}
  </section>;
}
