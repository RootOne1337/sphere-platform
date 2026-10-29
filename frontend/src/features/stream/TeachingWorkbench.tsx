'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Circle, Download, Keyboard, MousePointer2, Square, Video, Wifi } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/lib/store';
import { StreamQualityControl } from './StreamQualityControl';
import { TeachingContacts, type TeachingInput, type TeachingPoint } from './teachingContacts';
import { calibrated, calibrateProfile, calibrationNames, cameraContact, defaultTeachingProfile, fromPercent, keyLabel, movementTargets, profileIssue, teachingKeys, teachingRole, vehicleButtons, type CalibrationTarget, type TeachingKeyRole, type TeachingProfile } from './teachingKeymap';
import { TeachingKeyBindings } from './TeachingKeyBindings';
import { connectTeaching, type TeachingConnection } from './teachingConnection';
import type { DirectProbeResult } from './directProbe';
import { TeachingReview, type TeachingClipChoice } from './TeachingReview';
import { TeachingScenePreview } from './TeachingScenePreview';
import { teachingTitle } from './teachingMetadata';
import {TeachingCaptureSetup,type CaptureQuality} from './TeachingCaptureSetup';
import {TeachingNavigation} from './TeachingNavigation';
import {TeachingLocalWorker} from './TeachingLocalWorker';
import type {ReconstructionJob} from './reconstructionClient';
import type {RouteSource} from './routeSource';
import {walkingCalibrationIssue,walkingCameraIssue,walkingStickTarget,type WalkInputLease} from './walkPilot';

type Phase = 'idle' | 'connecting' | 'preview' | 'opening' | 'controlling' | 'piloting' | 'arming' | 'recording' | 'stopping' | 'finished';
const newId = () => crypto.randomUUID().replaceAll('-', '');
const active = (phase: Phase) => ['opening','controlling','piloting','arming','recording','stopping'].includes(phase);
const inputEnabled = (phase: Phase) => phase === 'controlling' || phase === 'recording';
const stopReasons: Record<string,string> = { page_hidden: 'страница скрыта', window_focus_lost: 'окно потеряло фокус', input_focus_lost: 'фокус управления потерян при удержании', connection_closed: 'соединение закрыто', video_stalled: 'нет свежих кадров', pointer_cancelled: 'касание отменено', keyframe_start_timeout: 'ключевой кадр не получен за 12 секунд' };
Object.assign(stopReasons,{contact_video_stale:'ввод остановлен: видеокадр старше 250 мс',contact_channel_closed:'канал ввода закрыт',contact_ack_timeout:'Android не подтвердил команду за 500 мс',contact_ready_timeout:'Android не подтвердил готовность ввода за 6 секунд'});
stopReasons.native_closed_unexpectedly='Android завершил сеанс ввода. Управление выключено';
Object.assign(stopReasons,{encoded_geometry_or_codec_changed:'изменился размер или кодек входящего H.264',recorder_worker_failed:'сбой обработчика записи',recording_write_failed:'не удалось записать данные в хранилище браузера',capture_renewal_unconfirmed:'сервер не подтвердил продление видеосеанса',release_unknown:'освобождение ввода не подтверждено'});
Object.assign(stopReasons,{recording_library_limit:'в библиотеке уже 100 записей; сохраните нужные в архив перед освобождением места',recording_storage_full:'закончилась квота хранилища браузера',recording_storage_denied:'браузер запретил доступ к хранилищу',recording_exists:'запись с таким идентификатором уже существует',finalization_unconfirmed:'завершение записи не подтверждено'});

export function TeachingWorkbench({ deviceId, readOnly }: { deviceId: string; readOnly: boolean }) {
  const token = useAuthStore(s => s.accessToken), sessionVersion = useAuthStore(s => s.sessionVersion);
  const user = useAuthStore(s => s.user);
  const [storageScope, setStorageScope] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('idle'); const phaseRef = useRef<Phase>('idle');
  const [notice, setNotice] = useState('Подключите поток и нажмите «Записать маршрут». По умолчанию управляйте игрой в эмуляторе.');
  const [native, setNative] = useState('Не открыт'); const [result, setResult] = useState<DirectProbeResult | null>(null);
  const [inputRtt,setInputRtt]=useState<number|null>(null);
  const [profile, setProfile] = useState<TeachingProfile>(defaultTeachingProfile); const profileRef = useRef(profile); profileRef.current = profile;
  const [calibrate, setCalibrate] = useState<CalibrationTarget | null>(null);
  const [bindingTarget,setBindingTarget]=useState<TeachingKeyRole|null>(null);
  const [hudHidden, setHudHidden] = useState(false);
  const [externalRecording, setExternalRecording] = useState(true);
  const externalActive = useRef(false);
  const externalOwnerReleased = useRef(false), externalVideoStarted = useRef(false);
  const [exportBusy,setExportBusy] = useState(false);
  const [title, setTitle] = useState('');
  const [minutes, setMinutes] = useState(10);
  const [progress, setProgress] = useState({ frames: 0, bytes: 0, seconds: 0 });
  const [encoded, setEncoded] = useState('Encoded-приём ожидается');
  const [lastCapture,setLastCapture]=useState<{title:string;complete:boolean;reason:string|null;frames:number;seconds:number}|null>(null);
  const [ready, setReady] = useState(false); const [clip, setClip] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [workspaceMode,setWorkspaceMode]=useState<'capture'|'review'|'live'>('capture');
  const [captureQuality,setCaptureQuality]=useState<CaptureQuality|null>(null);
  const [captureTargetFps,setCaptureTargetFps]=useState<number|null>(null);
  const [navigationBinding,setNavigationBinding]=useState<{job:ReconstructionJob;clip:string;scope:string}|null>(null);
  const [clipChoices,setClipChoices]=useState<TeachingClipChoice[]>([]);
  const [routeSource,setRouteSource]=useState<RouteSource|null>(null);
  const [prepareAfterRecording,setPrepareAfterRecording]=useState(true),[autoPrepare,setAutoPrepare]=useState<{clip:string;scope:string}|null>(null);
  const consumedAutoPrepare=useCallback(()=>setAutoPrepare(null),[]);
  const routeChanged=useCallback((job:ReconstructionJob|null,sourceClip:string|null,scope:string|null)=>setNavigationBinding(job&&sourceClip&&scope?{job,clip:sourceClip,scope}:null),[]);
  const clipsChanged=useCallback((items:TeachingClipChoice[])=>setClipChoices(items),[]);
  const navigationJob=navigationBinding?.clip===clip&&navigationBinding.scope===storageScope?navigationBinding.job:null;
  const video = useRef<HTMLVideoElement>(null); const host = useRef<HTMLDivElement>(null);
  const videoHolder=useRef<HTMLDivElement>(null),[pinLiveVideo,setPinLiveVideo]=useState(false);
  useEffect(()=>{
    setPinLiveVideo(false);const holder=videoHolder.current;
    if(workspaceMode!=='live'||calibrate||bindingTarget||!holder||typeof IntersectionObserver==='undefined')return;
    // Keep the SAME video element presented when the operator scrolls to the
    // map. A second peer/video would break source/age and input ownership.
    const observer=new IntersectionObserver(entries=>setPinLiveVideo(!entries[0]?.isIntersecting),{threshold:.05});
    observer.observe(holder);return()=>observer.disconnect();
  },[workspaceMode,calibrate,bindingTarget]);
  const connection = useRef<TeachingConnection | null>(null), controller = useRef<TeachingContacts | null>(null);
  const abort = useRef<AbortController | null>(null), stopPromise = useRef<Promise<void> | null>(null);
  const keys = useRef(new Set<string>()), mouse = useRef<number | null>(null), attached = useRef(false);
  const mouseContact = useRef<1|2>(1);
  const recordConfig = useRef<Record<string, unknown> | null>(null);
  const finalize = useRef<(() => void) | null>(null);
  const armSent = useRef(false);
  const armDeadline=useRef<ReturnType<typeof setTimeout>|null>(null);
  const clearArmDeadline=()=>{if(armDeadline.current!==null)clearTimeout(armDeadline.current);armDeadline.current=null;};
  const expectedOwnerClose = useRef(false), ownerGeneration = useRef(0);
  const stopCallback = useRef<(reason?: string) => Promise<void>>(async () => {});
  const change = (value: Phase) => { phaseRef.current = value; setPhase(value); };
  useEffect(() => {
    let retired = false; setStorageScope(null);
    if (user?.id && user.org_id && crypto.subtle) {
      void crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([user.org_id,user.id])))
        .then(bytes => { if(!retired)setStorageScope(Array.from(new Uint8Array(bytes).slice(0,16),v=>v.toString(16).padStart(2,'0')).join('')); })
        .catch(() => { if(!retired)setNotice('Локальное хранилище для текущего аккаунта недоступно.'); });
    }
    return () => { retired = true; };
  }, [user?.id,user?.org_id]);

  const stop = (reason?: string): Promise<void> => {
    if (stopPromise.current) return stopPromise.current;
    if (!active(phaseRef.current)) return Promise.resolve();
    clearArmDeadline();
    change('stopping'); keys.current.clear(); mouse.current = null;
    stopPromise.current = (async () => {
      expectedOwnerClose.current=true;
      const confirmed = await controller.current?.close() ?? false;
      expectedOwnerClose.current=false;
      const conn = connection.current;
      if (conn && armSent.current) {
        await new Promise<void>(resolve => {
          const timeout = setTimeout(() => { finalize.current = null; setNotice('Финализация не подтверждена. Запись не считается завершённой.'); resolve(); }, 10000);
          finalize.current = () => { clearTimeout(timeout); finalize.current = null; resolve(); };
          conn.worker.postMessage({ type: 'stop', confirmed, reason: reason ?? null });
        });
      }
      conn?.setExternalCapture?.(false); externalActive.current = false;
      if (armSent.current) { change('finished'); setReady(false); }
      else { controller.current = null; stopPromise.current = null; change(confirmed ? 'preview' : 'finished'); setNotice(confirmed ? 'Управление выключено. Все контакты освобождены.' : 'Освобождение ввода не подтверждено. Подключите поток заново.'); if(!confirmed)setReady(false); }
      if (reason) setNotice(`Остановлено: ${stopReasons[reason] ?? reason}. ${armSent.current ? 'Проверьте статус материала.' : 'Для продолжения снова включите управление.'}`);
    })();
    return stopPromise.current;
  };
  stopCallback.current = stop;
  const disconnect = async () => {
    await stopCallback.current('connection_closed');
    abort.current?.abort(); abort.current = null;
    connection.current?.close(); connection.current?.worker.terminate(); connection.current = null;
    controller.current = null; attached.current = false; armSent.current = false; setReady(false); setResult(null); change('idle');
  };
  useEffect(() => {
    const timer = setInterval(() => {setReady(connection.current?.fresh() === true && attached.current);
      setInputRtt(connection.current?.controlRttMs?.()??null);}, 200);
    const hidden = () => { if (document.hidden && !externalActive.current) void stopCallback.current('page_hidden'); };
    const blur = () => {
      if(!active(phaseRef.current))return;
      if(keys.current.size || mouse.current !== null) { void stopCallback.current('window_focus_lost'); return; }
      if(externalActive.current && ['opening','arming','recording'].includes(phaseRef.current))return;
      // Embedded Rerun focuses its canvas at startup. Moving between documents
      // inside the same focused page is not leaving the app. Held input is never exempt.
      queueMicrotask(()=>{
        const target=document.activeElement;
        if(document.hasFocus() && target?.tagName==='IFRAME' && target.getAttribute('title')==='3D-сцена маршрута Rerun')return;
        if(active(phaseRef.current))void stopCallback.current('window_focus_lost');
      });
    };
    document.addEventListener('visibilitychange', hidden); window.addEventListener('blur', blur);
    return () => {
      ownerGeneration.current++;
      clearArmDeadline();
      clearInterval(timer); document.removeEventListener('visibilitychange', hidden); window.removeEventListener('blur', blur);
      const conn = connection.current, control = controller.current, request = abort.current;
      void (async () => {
        if (active(phaseRef.current) && conn) {
          const confirmed = await control?.close() ?? false;
          conn.worker.postMessage({ type: 'stop', confirmed, reason: 'page_unmounted' });
          setTimeout(() => conn.worker.terminate(), 10000);
        } else conn?.worker.terminate();
        conn?.close(); request?.abort();
      })();
    };
  }, [deviceId, sessionVersion]);
  useEffect(() => { if (readOnly) void stopCallback.current('control_permission_removed'); }, [readOnly]);

  const connect = async () => {
    if (!token || !storageScope || readOnly || phaseRef.current === 'connecting') return;
    // Chromium may suspend presentation callbacks for a video outside the viewport.
    // Bring the operator's screen into view before qualifying fresh frames.
    video.current?.scrollIntoView?.({block:'center',behavior:'auto'});
    await disconnect(); stopPromise.current = null; setResult(null); setCaptureQuality(null); setCaptureTargetFps(null); change('connecting');
    setNative('Не открыт'); setNotice('Подключаем один прямой поток. Ввод ещё выключен.');
    const request = new AbortController(); abort.current = request;
    try {
      const conn = await connectTeaching(deviceId, token, video.current!, request.signal, setResult,
        reason => { if (request.signal.aborted) return; setNotice(`Транспорт остановлен: ${reason}`); void stopCallback.current(reason).then(() => {
          connection.current?.close(); if (!active(phaseRef.current)) setReady(false);
        }); }, message => {
          if (request.signal.aborted) return;
          if (message.type === 'attached') attached.current = true;
          if (message.type === 'armed' && externalActive.current) {
            expectedOwnerClose.current=true;
            void (async()=>{
              const closed=await controller.current?.close() ?? false;
              expectedOwnerClose.current=false;
              if(!closed) { void stopCallback.current('release_unknown'); return; }
              externalOwnerReleased.current=true;
              if(externalVideoStarted.current && phaseRef.current==='arming') {
                clearArmDeadline();
                change('recording');setNative('CLOSED · освобождено');
                setNotice('Идёт запись видео. Управляйте в эмуляторе: внешние нажатия не записываются.');
              }
            })();
          }
          if (message.type === 'recording') {
            clearArmDeadline();
            if(externalActive.current){
              externalVideoStarted.current=true;
              if(!externalOwnerReleased.current){setNotice('Видео началось; освобождаем ввод Sphere перед управлением в эмуляторе.');return;}
            }
            change('recording'); setNotice(externalActive.current ? 'Идёт запись видео. Управляйте в эмуляторе: внешние нажатия не записываются.' : 'Идёт запись оригинального видео и подтверждённых действий.'); if(!externalActive.current)video.current?.focus({preventScroll:true});
          }
          if (message.type === 'progress') setProgress({ frames: Number(message.frames), bytes: Number(message.bytes), seconds: Number(message.seconds) });
          if (message.type==='progress'&&message.capture_quality)setCaptureQuality(message.capture_quality as CaptureQuality);
          if (message.type === 'limit_reached') { setNotice('Достигнут выбранный предел. Освобождаем ввод и сохраняем запись.'); void stopCallback.current(); }
          if (message.type === 'encoded_status') setEncoded(`Encoded ${Number(message.frames)} · ${String(message.kind)} · NAL ${Array.isArray(message.nal_types) ? message.nal_types.join('/') : '?'} · ${String(message.width)}×${String(message.height)}`);
          if (message.type === 'failed') { setNotice(`Ошибка записи: ${String(message.reason)}`); void stopCallback.current(String(message.reason)); }
          if (message.type === 'finalized') {
            clearArmDeadline();
            setClip(typeof message.id === 'string' && /^[0-9a-f]{32}$/.test(message.id) ? message.id : null); setRefresh(v => v + 1);
            const manifest = message.manifest as { complete?: boolean; failure?: string; frames?: number; media_duration_ticks_90k?: number; files?: Record<string,{bytes:number}>;capture_quality?:CaptureQuality };
            if(manifest.capture_quality)setCaptureQuality(manifest.capture_quality);
            if(typeof manifest.frames === 'number')setProgress({ frames: manifest.frames, bytes: manifest.files?.['video.h264']?.bytes ?? 0, seconds: (manifest.media_duration_ticks_90k ?? 0)/90000 });
            const finalizedConfig=recordConfig.current;
            setLastCapture({title:String(finalizedConfig?.title??'Запись'),complete:manifest.complete===true,reason:manifest.complete?null:manifest.failure??'finalization_unconfirmed',frames:manifest.frames??0,seconds:(manifest.media_duration_ticks_90k??0)/90000});
            if(manifest.complete&&finalizedConfig&&message.id===finalizedConfig.id&&finalizedConfig.prepare_after_recording===true
              &&typeof finalizedConfig.storage_scope==='string')setAutoPrepare({clip:message.id as string,scope:finalizedConfig.storage_scope});
            setNotice(manifest.complete ? 'Материал сохранён. Видео и журнал готовы к просмотру.' : `Материал неполный: ${manifest.failure ?? 'нет подтверждения'}. Для повторения маршрута не допущен.`);
            finalize.current?.();
          }
        });
      if (request.signal.aborted) { conn.close(); conn.worker.terminate(); return; }
      connection.current = conn; change('preview');
      setNotice('Проверьте игру в потоке. Для записи из эмулятора достаточно нажать «Записать маршрут»; веб-управление включается отдельно.');
    } catch (error) { request.abort(); change('idle'); setNotice(`Подключение не готово: ${error instanceof Error ? error.message : 'ошибка'}`); }
  };
  const openInput = (mode: 'control' | 'record', conn: TeachingConnection) => {
    const binding = conn.binding(), endpoint = conn.endpoint();
    const generation=ownerGeneration.current;
    if(!binding || !endpoint)throw Error('Ввод ещё не готов');
    controller.current = new TeachingContacts(endpoint, binding, conn.fresh,
      (event: TeachingInput) => { if(armSent.current)conn.worker.postMessage({ type: 'input', event }); }, (state, reason) => {
        if(generation!==ownerGeneration.current || connection.current!==conn)return;
        conn.observeControl?.(state==='failed'?'fenced':state,reason);
        setNative(state === 'ready' ? 'READY · 3 контакта' : state === 'closed' ? 'CLOSED · освобождено' : state);
        if (state === 'ready' && phaseRef.current === 'opening') {
          if(mode === 'control') { change('controlling'); setNotice('Управление включено без записи. Щёлкните по экрану: назначенные клавиши и мышь.'); video.current?.focus({preventScroll:true}); }
          else {
            change('arming'); armSent.current = true; conn.worker.postMessage({ type: 'arm', config: recordConfig.current });
            setNotice('Ждём ключевой H264-кадр. Не удерживайте клавиши до начала записи.');
            clearArmDeadline();
            armDeadline.current=setTimeout(() => { if (phaseRef.current === 'arming') void stopCallback.current('keyframe_start_timeout'); }, 12000);
          }
        }
        if (state === 'failed') void stopCallback.current(reason ?? 'native_input_failed');
        if (state === 'closed' && active(phaseRef.current) && phaseRef.current!=='stopping' && !expectedOwnerClose.current) void stopCallback.current('native_closed_unexpectedly');
      },rtt=>conn.observeControl?.('ready',undefined,rtt));
  };
  const enableControl = () => {
    const conn = connection.current;
    if(readOnly || phaseRef.current !== 'preview' || !conn?.fresh() || !attached.current || calibrate)return;
    const binding=conn.binding();if(!binding)return;
    const issue=profileIssue(profileRef.current,binding);if(issue){setNotice(issue);return;}
    stopPromise.current = null; change('opening');
    try { openInput('control',conn); } catch { void stop('contact_protocol_unavailable'); }
  };
  const openWalkInput = async (signal:AbortSignal,journal:(event:TeachingInput)=>void):Promise<WalkInputLease> => {
    const conn=connection.current,b=conn?.binding(),endpoint=conn?.endpoint(),p=profileRef.current;
    if(signal.aborted||readOnly||phaseRef.current!=='preview'||!conn?.fresh()||!attached.current||!b||!endpoint
      ||walkingCalibrationIssue(p,b)||!result||!['host','nat'].includes(result.path))throw Error('walk_input_not_ready');
    stopPromise.current=null;change('opening');
    let released=false,settle:(lease:WalkInputLease)=>void=()=>{};
    const opened=new Promise<WalkInputLease>(resolve=>{settle=resolve;});
    const lease:WalkInputLease={
      active:()=>phaseRef.current==='piloting'&&controller.current===control&&connection.current===conn&&control.isReady
        &&(conn.fresh()||conn.idleInputFresh?.()===true)&&!signal.aborted,
      failure:()=>control.failureReason,
      canLook:()=>control.isNeutral,
      look:(fraction,notAfter)=>{
        if(!lease.active()||walkingCameraIssue(p,b)||!p.look||!Number.isFinite(fraction)||Math.abs(fraction)>.04||!control.isNeutral)return Promise.resolve(false);
        const origin=fromPercent(p.look,b),x=origin.x+Math.round(fraction*Math.min(b.width,b.height));
        return control.horizontalStroke(origin,x,notAfter);
      },
      set:vector=>{
        if(!lease.active())throw Error('walk_native_closed');
        if(Math.hypot(...vector)>0&&!conn.fresh())throw Error('contact_video_stale');
        const {center,target}=walkingStickTarget(p,b,vector);
        if(target&&!control.hasContact(0))control.set(0,center);
        control.set(0,target);
      },
      close:async()=>{await stopCallback.current();return released;},
    };
    const generation=ownerGeneration.current;
    const control=new TeachingContacts(endpoint,b,conn.fresh,event=>{journal(event);if(event.stage==='closed')released=event.outcome==='closed';},(state,reason)=>{
      if(generation!==ownerGeneration.current||connection.current!==conn)return;
      conn.observeControl?.(state==='failed'?'fenced':state,reason);
      setNative(state==='ready'?'READY · пеший тест':state==='closed'?'CLOSED · освобождено':state);
      if(state==='ready'&&phaseRef.current==='opening'&&!signal.aborted){change('piloting');settle(lease);}
      if(['failed','closed','closing'].includes(state))settle(lease);
      if(state==='failed')queueMicrotask(()=>{void stopCallback.current(reason??'walk_native_closed');});
      if(state==='closed'&&active(phaseRef.current)&&phaseRef.current!=='stopping'&&!expectedOwnerClose.current)queueMicrotask(()=>{void stopCallback.current('walk_native_closed');});
    },rtt=>conn.observeControl?.('ready',undefined,rtt),()=>conn.idleInputFresh?.()===true);
    controller.current=control;
    const cancelled=()=>{settle(lease);void stopCallback.current();};
    signal.addEventListener('abort',cancelled,{once:true});
    if(signal.aborted)cancelled();
    try{return await opened;}finally{if(signal.aborted)signal.removeEventListener('abort',cancelled);}
  };
  const record = async () => {
    const conn = connection.current, binding = conn?.binding(), endpoint = conn?.endpoint();
    if (readOnly || !storageScope || !['preview','controlling'].includes(phaseRef.current) || !conn?.fresh() || !binding || !endpoint || !attached.current) return;
    if(phaseRef.current==='controlling'&&(keys.current.size||mouse.current!==null||!controller.current?.isNeutral)){setNotice('Отпустите клавиши и мышь перед началом записи.');return;}
    // Freeze the video-only policy before any await: focus can leave for
    // LDPlayer while storage or the neutral input-owner release is pending.
    externalActive.current=externalRecording;
    conn.setExternalCapture?.(externalRecording);
    const setupFailed=(message:string)=>{conn.setExternalCapture?.(false);externalActive.current=false;change('preview');setNotice(message);};
    if(phaseRef.current === 'controlling') {
      if(keys.current.size || mouse.current !== null || !controller.current?.isNeutral) { setNotice('Отпустите клавиши и мышь перед началом записи.'); return; }
      change('opening');expectedOwnerClose.current=true; const closed = await controller.current.close();expectedOwnerClose.current=false;
      if((phaseRef.current as Phase) !== 'opening' || connection.current !== conn)return;
      if(!closed){conn.setExternalCapture?.(false);externalActive.current=false;change('finished');setReady(false);setNotice('Освобождение прежнего ввода не подтверждено. Подключите поток заново.');return;}
      controller.current = null;
    }
    change('opening');
    let storage: StorageEstimate;
    try { storage = await navigator.storage.estimate(); } catch { if(phaseRef.current==='opening'&&connection.current===conn)setupFailed('Не удалось проверить квоту браузера.'); return; }
    if ((phaseRef.current as Phase) !== 'opening' || connection.current !== conn) return;
    const maxBytes = minutes === 2 ? 512*1024*1024 : 2*1024*1024*1024;
    if ((storage.quota ?? 0) - (storage.usage ?? 0) < maxBytes + 100*1024*1024) { setupFailed(`Нужно ${minutes === 2 ? '612 МБ' : '2,1 ГБ'} свободной квоты браузера. Выберите меньший предел или экспортируйте старые материалы.`); return; }
    const p = profileRef.current, issue=externalRecording?null:profileIssue(p,binding);
    if(issue){setupFailed(issue);return;}
    const id = newId(); setProgress({ frames: 0, bytes: 0, seconds: 0 });setCaptureQuality(null);setLastCapture(null); stopPromise.current = null;
    recordConfig.current = { id, storage_scope: storageScope, device_id: deviceId, width: binding.width, height: binding.height,
      capture_epoch: binding.captureEpoch, title: teachingTitle(title,id,Date.now()), profile: p,
      source: 'direct_webrtc_h264', target_fps: captureTargetFps, actual_fps_unverified: true,
      input_capture: externalRecording ? 'external_unobserved' : 'sphere_confirmed',
      prepare_after_recording: prepareAfterRecording,
      hud_hidden_declared: hudHidden, contact_roles: p.mode==='stick'?['stick','camera','action']:['throttle_or_brake','steering','camera_or_action'],
      max_duration_ms: minutes*60000, max_bytes: maxBytes, max_frames: minutes*3600 };
    externalActive.current=externalRecording;externalOwnerReleased.current=false;externalVideoStarted.current=false;
    change('opening'); setNotice('Открываем три контакта. Требуется APK 1.2.89 или новее с contact_protocol=1.');
    try {
      openInput('record',conn);
    } catch { void stop('contact_protocol_unavailable'); }
  };
  const updateStick = () => {
    const binding = connection.current?.binding(); if (!binding) return;
    const p = profileRef.current;
    const targets=movementTargets(keys.current,p,binding);
    // A floating joystick takes its origin from DOWN. Establish the centre once,
    // then retain the same contact while changing direction/speed with MOVE.
    if (targets.primary && targets.stick && !controller.current?.hasContact(0)) controller.current?.set(0, targets.stick);
    controller.current?.set(0, targets.primary);
    if(targets.secondary!==undefined)controller.current?.set(1,targets.secondary);
  };
  const key = (event: React.KeyboardEvent, down: boolean) => {
    if (event.code === 'Escape') { event.preventDefault(); void stop(); return; }
    const role=teachingRole(event.code,profileRef.current);
    if (!inputEnabled(phaseRef.current) || externalActive.current || !role) return;
    event.preventDefault(); if (event.repeat || keys.current.has(event.code) === down) return;
    const binding=connection.current?.binding(), mapping=profileRef.current;
    if(role==='action'&&down&&mapping.mode==='vehicle_buttons') {
      if(mouse.current!==null){setNotice('Отпустите мышь, чтобы использовать дополнительное действие.');return;}
      if(!binding||!calibrated(mapping,binding,'action')){setNotice('Сначала укажите экранную зону дополнительного действия транспорта.');return;}
    }
    if (down) keys.current.add(event.code); else keys.current.delete(event.code);
    if (role === 'action') {
      const b = connection.current?.binding(), p = profileRef.current;
      if (b) controller.current?.set(2, down ? fromPercent({x:p.action_x,y:p.action_y},b) : null);
    } else updateStick();
  };
  const point = (event: React.PointerEvent<HTMLVideoElement>): TeachingPoint | null => {
    const b = connection.current?.binding(); if (!b) return null;
    const box = event.currentTarget.getBoundingClientRect(), scale = Math.min(box.width / b.width, box.height / b.height);
    const x = (event.clientX-box.left-(box.width-b.width*scale)/2)/scale;
    const y = (event.clientY-box.top-(box.height-b.height*scale)/2)/scale;
    return x >= 0 && y >= 0 && x < b.width && y < b.height ? { x: Math.floor(x), y: Math.floor(y) } : null;
  };
  const field = 'w-full rounded-lg border border-input bg-background px-3 py-2 text-sm';
  const toolbarButton = 'h-auto min-h-9 whitespace-normal px-2 py-2 text-xs sm:text-sm';
  const binding=connection.current?.binding(), mappingIssue=binding?profileIssue(profile,binding):null, mappedKeys=teachingKeys(profile);
  const switchMode=async(next:'capture'|'review'|'live')=>{
    if(active(phaseRef.current)||exportBusy||phaseRef.current==='connecting')return;
    if(next==='review')await disconnect();
    setWorkspaceMode(next);
  };
  const calibrationMarkers=binding?(profile.mode==='vehicle_buttons'
    ?vehicleButtons.filter(target=>calibrated(profile,binding,target)).map(target=>({...fromPercent(profile.vehicle[target],binding),label:keyLabel(mappedKeys[target])}))
    :calibrated(profile,binding,'stick')?[{...fromPercent({x:profile.stick_x,y:profile.stick_y},binding),label:['forward','left','reverse','right'].map(role=>keyLabel(mappedKeys[role as keyof typeof mappedKeys])).join('')}]:[]):[];
  if(binding&&calibrated(profile,binding,'action'))calibrationMarkers.push({...fromPercent({x:profile.action_x,y:profile.action_y},binding),label:keyLabel(mappedKeys.action)});
  if(binding&&profile.look&&calibrated(profile,binding,'look'))calibrationMarkers.push({...fromPercent(profile.look,binding),label:'Камера ↔'});
  const chooseCalibration=(target:CalibrationTarget)=>{setBindingTarget(null);setCalibrate(target);video.current?.scrollIntoView({block:'center',behavior:'smooth'});};
  const chosenClip=clipChoices.find(item=>item.id===clip);
  useEffect(()=>{
    if(phase!=='finished'||!autoPrepare||autoPrepare.clip!==clip||autoPrepare.scope!==storageScope)return;
    // Finalized COMPLETE and CLOSED precede this effect. Release the old
    // encoded receiver before offline processing; no new Android input opens.
    abort.current?.abort();abort.current=null;connection.current?.close();connection.current?.worker.terminate();connection.current=null;
    controller.current=null;attached.current=false;armSent.current=false;setReady(false);setResult(null);change('idle');setWorkspaceMode('review');
  },[phase,autoPrepare,clip,storageScope]);
  const workflow=[
    {mode:'capture' as const,label:'1 · Запись',detail:'Покажите путь в игре',status:phase==='recording'?'Идёт запись':chosenClip?`Выбрано: ${chosenClip.title}`:'Ожидает запись'},
    {mode:'review' as const,label:'2 · Сцена',detail:'Проверьте запись и ориентиры',status:navigationJob?'Связана с записью':'Выберите проход'},
    {mode:'live' as const,label:'3 · Направление',detail:'Сверьте путь с живым кадром',status:'Наблюдение / пеший тест'},
  ];
  return <div ref={host} className="space-y-4" aria-label="Запись учебного маршрута">
    <section className="overflow-hidden rounded-2xl border border-sky-500/20 bg-gradient-to-br from-sky-500/10 via-card to-emerald-500/5 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-[.2em] text-sky-500">Sphere · студия маршрутов</p><h2 className="mt-1 text-xl font-semibold tracking-tight">От записи к проверке пути</h2><p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">Запишите проход, подготовьте его и проверьте ориентиры на живом экране. Автоматический повтор пока не подтверждён.</p></div><span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-3 py-1 text-[11px] font-medium text-amber-600 dark:text-amber-400">Ручная проверка</span></div>
      <nav aria-label="Режим студии маршрутов" className="mt-4 grid gap-2 md:grid-cols-3">{workflow.map(({mode,label,detail,status})=><button key={mode} type="button" aria-pressed={workspaceMode===mode} aria-current={workspaceMode===mode?'step':undefined} disabled={active(phase)||exportBusy||phase==='connecting'} onClick={()=>{void switchMode(mode);}} className={`group min-w-0 rounded-xl border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-60 ${workspaceMode===mode?'border-sky-500/60 bg-sky-500/10 shadow-sm':'border-border bg-background/55 hover:border-sky-500/35 hover:bg-background'}`}><span className="flex items-center justify-between gap-2 text-sm font-semibold"><span>{label}</span><ArrowRight size={15} className={workspaceMode===mode?'text-sky-500':'text-muted-foreground'}/></span><span className="mt-1 block text-xs text-muted-foreground">{detail}</span><span className="mt-2 block truncate text-[11px] font-medium text-sky-600 dark:text-sky-400" title={status}>{status}</span></button>)}</nav>
    </section>
    <TeachingLocalWorker/>
    <div className="space-y-4">
    <div aria-label="Панель записи" className="sticky top-16 z-30 flex flex-wrap items-center gap-2 rounded-2xl border border-border bg-card/95 p-3 shadow-xl backdrop-blur">
      <div className="grid w-full grid-cols-2 gap-2 lg:flex lg:w-auto lg:flex-wrap">
      <Button className={toolbarButton} variant="outline" disabled={readOnly || exportBusy || !storageScope || active(phase) || phase === 'connecting'} onClick={() => { if(workspaceMode==='review')setWorkspaceMode('capture');void connect(); }}>{phase === 'idle' ? 'Подключить поток' : 'Подключить заново'}</Button>
      <Button className={toolbarButton} variant="outline" disabled={readOnly || exportBusy || phase !== 'preview' || !ready || !!calibrate || !!bindingTarget || !!mappingIssue} onClick={enableControl}><Keyboard size={15} className="mr-2 shrink-0" />Включить управление</Button>
      <Button className={toolbarButton} disabled={workspaceMode!=='capture'||readOnly || exportBusy || !['preview','controlling'].includes(phase) || !ready || !!calibrate || !!bindingTarget || (!externalRecording && !!mappingIssue)} onClick={() => { void record(); }}><Circle size={15} className="mr-2 shrink-0 text-red-500" />Записать маршрут</Button>
      <Button className={toolbarButton} variant="destructive" disabled={!active(phase) || phase === 'stopping'} onClick={() => { void stop(); }}><Square size={15} className="mr-2 shrink-0" />{phase === 'stopping' ? 'Освобождение и сохранение…' : 'Остановить · Esc'}</Button>
      </div>
      {(phase==='recording'||phase==='finished')&&<span className="rounded-lg bg-muted px-2 py-1 font-mono text-xs tabular-nums">{progress.seconds.toFixed(1)} с · {progress.frames} кадров{progress.seconds>0?` · ${(progress.frames/progress.seconds).toFixed(1)} средних FPS`:''}</span>}
      {workspaceMode==='capture'&&<span className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-medium">{externalRecording?'Видео из эмулятора · фокус веба не требуется':'Видео + управление в вебе · потеря фокуса остановит сеанс'}</span>}
      <p role="status" className="min-w-[220px] flex-1 text-xs leading-5 text-muted-foreground">{readOnly ? 'Для записи требуется право stream:control.' : exportBusy?'Обрабатываем сохранённый материал. Дождитесь завершения перед новым управлением.':calibrate ? `Укажите ${calibrationNames[calibrate]} на экране. Касание в игру не отправляется.` : (!externalRecording && mappingIssue) || notice}</p>
    </div>
    {lastCapture&&<div aria-label="Результат последней записи" className={`rounded-xl border p-3 text-sm ${lastCapture.complete?'border-emerald-500/30 bg-emerald-500/5':'border-red-500/40 bg-red-500/5'}`}><p className="font-semibold">{lastCapture.title} · {lastCapture.complete?'Сохранена':'Неполная запись'} · {lastCapture.seconds.toFixed(1)} с · {lastCapture.frames} кадров</p>{lastCapture.reason&&<p className="mt-1 text-xs">Причина: {stopReasons[lastCapture.reason]??lastCapture.reason} <code>({lastCapture.reason})</code>. Сохранённая часть остаётся в библиотеке.</p>}</div>}
    <div hidden={workspaceMode==='review'} className="space-y-4">
    {workspaceMode==='capture'&&<details className="group rounded-xl border border-sky-500/20 bg-sky-500/5"><summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"><span>Качество исходной записи</span><span className="text-xs font-normal text-muted-foreground">{captureQuality?.received_encoded_fps!=null?`${captureQuality.received_encoded_fps.toFixed(1)} FPS по записи`:'Профиль и фактические FPS · открыть настройки'}</span></summary><TeachingCaptureSetup key={`${deviceId}:${sessionVersion}`} deviceId={deviceId} disabled={readOnly||active(phase)||exportBusy} quality={captureQuality} onConfirmedTarget={setCaptureTargetFps}/></details>}
    <section className="rounded-2xl border border-border bg-card p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest text-primary">{workspaceMode==='live'?'Повторный проход':'Обучение маршруту'}</p><h2 className="mt-1 text-xl font-semibold">{workspaceMode==='live'?'Сверка с живым экраном':'Покажите путь один раз'}</h2><p className="mt-2 max-w-3xl text-sm text-muted-foreground">{workspaceMode==='live'?'Выберите проход. Наблюдение показывает линию без ввода; отдельный «Пеший тест» включает ограниченное управление стиком.':externalRecording?'Запишите видео, управляя в эмуляторе. Внешние нажатия недоступны журналу Sphere.':'Подготовьте игру с клавиатуры, включите запись и покажите маршрут. Видео и подтверждённые касания сохраняются вместе.'}</p></div><StreamQualityControl deviceId={deviceId} readOnly={readOnly || active(phase)} /></div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3"><Metric icon={<Wifi size={15} />} label="Транспорт" value={result ? `${result.path==='host'||result.path==='nat'?'Напрямую':result.path==='relay'?'Ретранслятор':'Путь уточняется'} · ${result.state}` : 'Не подключён'} /><Metric icon={<Keyboard size={15} />} label="Нативный ввод" value={`${native}${inputRtt===null?'':` · ACK ${inputRtt.toFixed(1)} мс`}`} /><Metric icon={<Video size={15} />} label="Записано" value={`${progress.seconds.toFixed(1)} с · ${progress.frames} кадров · ${(progress.bytes/1048576).toFixed(1)} МБ`} /></div>
      {result?.videoStats&&<><div aria-label="Фактические параметры приёма" className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground"><span>{result.videoStats.width??'—'} × {result.videoStats.height??'—'}</span><span>{result.videoStats.fps?.toFixed(1)??'—'} FPS приёма</span><span>{result.videoStats.bitrateBps==null?'—':(result.videoStats.bitrateBps/1e6).toFixed(2)} Мбит/с</span><span title="RTT выбранной пары ICE; это не задержка нажатия">RTC RTT {result.videoStats.networkRttMs?.toFixed(1)??'—'} мс</span><span title="Среднее время в буфере приёма за последний интервал">Буфер приёма {result.videoStats.jitterBufferMs?.toFixed(1)??'—'} мс</span><span title="Среднее время декодирования за последний интервал">Декодирование {result.videoStats.decodeMs?.toFixed(1)??'—'} мс</span></div><p className="mt-1 text-[11px] text-muted-foreground">Это метрики браузерного приёма; полная задержка Android → экран и нажатия здесь не измеряется.</p></>}
    </section>
    <div className={workspaceMode==='live'?'grid items-start gap-4 xl:grid-cols-[280px_minmax(0,1fr)]':'grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_300px]'}>
      <section className={`overflow-hidden rounded-2xl border border-border bg-card ${workspaceMode==='live'?'xl:sticky xl:top-56':''}`}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3 text-sm"><span className="font-medium">{phase === 'recording' ? '● Запись' : 'Прямой экран Android'}</span><span className="text-xs text-muted-foreground">{connection.current?.binding() ? `${connection.current.binding()!.width} × ${connection.current.binding()!.height}` : 'Размер ожидается'}</span></div>
        <div ref={videoHolder} className="relative aspect-video">
        <video ref={video} muted playsInline tabIndex={0} aria-label="Игровой экран: назначенные клавиши и мышь; Escape — остановить запись"
          className={`aspect-video max-h-[calc(100dvh-14rem)] scroll-mt-56 touch-none bg-black object-contain outline-none focus-visible:ring-2 focus-visible:ring-primary ${pinLiveVideo?'fixed bottom-6 left-6 z-50 w-60 rounded-xl border border-cyan-500/60 shadow-2xl':'w-full'}`}
          onKeyDown={e => key(e,true)} onKeyUp={e => key(e,false)} onContextMenu={e => e.preventDefault()}
          onBlur={() => { if (keys.current.size || mouse.current !== null) void stop('input_focus_lost'); }}
          onPointerDown={e => {
            const pos = point(e), b = connection.current?.binding(); if (!pos || !b) return;
            if (calibrate && !active(phase)) {
              setProfile(p => calibrateProfile(p,b,calibrate,pos)); setCalibrate(null); return;
            }
            if (!inputEnabled(phaseRef.current) || externalActive.current || mouse.current !== null || e.button !== 0) return;
            if(profileRef.current.mode==='vehicle_buttons'&&[...keys.current].some(code=>teachingRole(code,profileRef.current)==='action')){setNotice(`Отпустите ${keyLabel(teachingKeys(profileRef.current).action)}, чтобы двигать камеру мышью.`);return;}
            e.preventDefault(); e.currentTarget.focus(); e.currentTarget.setPointerCapture(e.pointerId);
            mouse.current = e.pointerId; mouseContact.current=cameraContact(profileRef.current);controller.current?.set(mouseContact.current,pos);
          }}
          onPointerMove={e => { if (mouse.current === e.pointerId) { const p = point(e); if(p) controller.current?.set(mouseContact.current,p); } }}
          onPointerUp={e => { if (mouse.current === e.pointerId) { mouse.current = null; controller.current?.set(mouseContact.current,null); e.currentTarget.releasePointerCapture(e.pointerId); } }}
          onPointerCancel={e => { if(!externalActive.current&&mouse.current===e.pointerId)void stop('pointer_cancelled'); }}
          onLostPointerCapture={e => { if (mouse.current === e.pointerId) void stop('pointer_capture_lost'); }} />
        {ready&&!active(phase)&&binding&&<svg aria-label="Проверенные точки управления" className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${binding.width} ${binding.height}`} preserveAspectRatio="xMidYMid meet">
          {calibrationMarkers.map(marker=><g key={marker.label} transform={`translate(${marker.x} ${marker.y})`}><circle r={Math.max(9,binding.height*.018)} fill="#020617cc" stroke="#38bdf8" strokeWidth={2}/><text textAnchor="middle" dominantBaseline="central" fill="white" fontSize={Math.max(9,binding.height*.018)}>{marker.label}</text></g>)}
        </svg>}
        {calibrate&&<p className="pointer-events-none absolute left-2 right-2 top-2 rounded-lg bg-background/95 px-3 py-2 text-sm text-primary">Укажите {calibrationNames[calibrate]}. Это только калибровка.</p>}
        </div>
        {workspaceMode==='live'&&<div className="space-y-2 border-t p-3 text-xs"><p className="font-medium">Стик для пешего теста</p><div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="outline" disabled={!ready||active(phase)} onClick={()=>{setProfile(p=>({...p,mode:'stick'}));chooseCalibration('stick');}}>Указать центр пешего стика</Button><Button size="sm" variant="outline" disabled={!ready||active(phase)} onClick={()=>chooseCalibration('look')}>Указать область поворота камеры</Button><label>Радиус, % короткой стороны <input aria-label="Радиус пешего стика" type="number" className="ml-2 w-16 rounded border bg-background p-1" value={profile.radius} min={1} max={20} step={.5} disabled={active(phase)} onChange={e=>{const n=Number(e.target.value);if(n>=1&&n<=20)setProfile(p=>({...p,radius:n}));}}/></label></div><p className="text-muted-foreground">Укажите центр на прямом экране выше. Калибровочное касание не отправляется в игру. Для автоповорота укажите свободную область вне стика и кнопок: используются только горизонтальные свайпы. Прыжок не управляется.</p></div>}
        <div className="flex flex-wrap gap-2 border-t border-border p-3 text-xs text-muted-foreground"><span className={`rounded-md px-2 py-1 ${inputEnabled(phase) && !externalActive.current ? 'bg-primary/15 text-primary' : 'bg-muted'}`}>{phase==='piloting'?'Пеший тест · стик управляется алгоритмом':externalActive.current ? 'Управление в эмуляторе · нажатия не записываются' : inputEnabled(phase) ? 'Управление включено · фокус на экране' : 'Управление выключено'}</span><span className="rounded-md bg-muted px-2 py-1">{profile.mode==='stick'?`${keyLabel(mappedKeys.forward)}/${keyLabel(mappedKeys.left)}/${keyLabel(mappedKeys.reverse)}/${keyLabel(mappedKeys.right)} · стик`:`${keyLabel(mappedKeys.forward)}/${keyLabel(mappedKeys.reverse)} · газ и тормоз · ${keyLabel(mappedKeys.left)}/${keyLabel(mappedKeys.right)} · руль`}</span>{profile.mode==='stick'&&<span className="rounded-md bg-muted px-2 py-1">{keyLabel(mappedKeys.slow)} · 40% скорости</span>}<span className="rounded-md bg-muted px-2 py-1">ЛКМ + движение · камера</span><span className="rounded-md bg-muted px-2 py-1">{keyLabel(mappedKeys.action)} · удержание кнопки</span></div>
        <details className="px-4 pb-3 text-xs text-muted-foreground"><summary>Диагностика приёма видео</summary>{encoded}</details>
      </section>
      {workspaceMode==='live'&&<TeachingNavigation key={navigationJob?.id??'none'} job={navigationJob} video={video} ready={ready} binding={binding??null} clips={clipChoices} clip={clip} scope={storageScope} sourceRecording={routeSource?.clip===clip&&routeSource.scope===storageScope?routeSource:null} onSelectClip={setClip} selectionDisabled={active(phase)||exportBusy||phase==='connecting'} onReview={()=>{void switchMode('review');}} walkInput={{open:openWalkInput,cameraIssue:walkingCameraIssue(profile,binding??null),issue:readOnly?'Нет права управления.':!result||!['host','nat'].includes(result.path)?'Для пешего теста нужен прямой поток.':walkingCalibrationIssue(profile,binding??null)??(phase==='preview'?null:'Сначала выключите ручное управление или запись.')}}/>}
      <aside hidden={workspaceMode==='live'} className="space-y-4 rounded-2xl border border-border bg-card p-4">
        <h3 className="font-semibold">Подготовка маршрута</h3>
        <label className="block space-y-1 text-sm"><span>Название</span><input className={field} value={title} placeholder="Автоматически: дата, время и номер записи" maxLength={128} disabled={active(phase)} onChange={e => setTitle(e.target.value)} /></label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={externalRecording} disabled={active(phase)} onChange={e=>setExternalRecording(e.target.checked)} /><span>Управляю в эмуляторе · только видео<br/><span className="text-xs text-muted-foreground">Можно переключиться в LDPlayer. Нажатия эмулятора не записываются; страница должна оставаться открытой.</span></span></label>
        <label className="block space-y-1 text-sm"><span>Схема управления</span><select className={field} value={profile.mode} disabled={active(phase)} onChange={e=>{setBindingTarget(null);setCalibrate(null);setProfile(p=>({...p,mode:e.target.value as TeachingProfile['mode']}));}}><option value="stick">Стик · ходьба / аналоговое управление</option><option value="vehicle_buttons">Транспорт · газ, тормоз, левый и правый руль</option></select></label>
        <TeachingKeyBindings profile={profile} disabled={readOnly||active(phase)} editing={bindingTarget} onEditingChange={role=>{setBindingTarget(role);if(role)setCalibrate(null);}} onChange={setProfile}/>
        <div className="space-y-2"><p className="text-sm font-medium">Калибровка касаний</p>
          {profile.mode==='stick'?<><Button variant="outline" className="w-full justify-start" disabled={!ready || active(phase)} onClick={() => chooseCalibration('stick')}><MousePointer2 size={15} className="mr-2" />Центр стика · {profile.stick_x.toFixed(1)} / {profile.stick_y.toFixed(1)}%</Button>
            <label className="block space-y-1 text-sm"><span>Радиус стика · % короткой стороны</span><input className={field} type="number" min={1} max={20} step={0.5} value={profile.radius} disabled={active(phase)} onChange={e => { const n = Number(e.target.value); if(n>=1&&n<=20) setProfile(p => ({...p,radius:n})); }} /></label></>
            :<>{vehicleButtons.map(target=><Button key={target} variant="outline" className="w-full justify-start" disabled={!ready||active(phase)} onClick={()=>chooseCalibration(target)}>{calibrationNames[target]} · {profile.vehicle[target].x.toFixed(1)} / {profile.vehicle[target].y.toFixed(1)}% {binding&&calibrated(profile,binding,target)?'✓':'· указать'}</Button>)}
              <p className="text-xs leading-5 text-muted-foreground">Сначала сядьте в транспорт и укажите четыре экранные кнопки. Координаты-примеры не включают управление. Клавиши указаны выше; камера мышью и дополнительное действие используются по очереди.</p></>}
          <Button variant="outline" className="w-full justify-start" disabled={!ready || active(phase)} onClick={() => chooseCalibration('action')}>{profile.mode==='vehicle_buttons'?`Доп. действие · ${keyLabel(mappedKeys.action)}`:'Кнопка действия'} · {profile.action_x.toFixed(1)} / {profile.action_y.toFixed(1)}%</Button>
          {calibrate&&<Button size="sm" variant="ghost" onClick={()=>setCalibrate(null)}>Отменить калибровку</Button>}
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={hudHidden} disabled={active(phase)} onChange={e=>setHudHidden(e.target.checked)} />HUD скрыт в игре</label>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={prepareAfterRecording} disabled={active(phase)} onChange={e=>setPrepareAfterRecording(e.target.checked)}/><span>После сохранения подготовить карту<span className="mt-1 block text-xs text-muted-foreground">Камеры и ориентиры рассчитываются локально один раз. Управление запускается отдельно.</span></span></label>
        <p className="text-xs leading-5 text-muted-foreground">Кнопки калибруйте до отключения HUD. Флажок сохраняет пометку в материале; он не скрывает интерфейс игры и не вырезает надписи из видео.</p>
        <p className="text-xs leading-5 text-muted-foreground">Перед качественным проходом: 1920 × 1080, рендер игры100%, стабильная камера. Сохраните одинаковые FOV и режим камеры для записи и повторения; DPI сам по себе не улучшает3D. Сначала подтвердите реальные30 FPS по записи.</p>
        <label className="block space-y-1 text-sm"><span>Предел записи</span><select className={field} value={minutes} disabled={active(phase)} onChange={e=>setMinutes(Number(e.target.value))}><option value={2}>2 минуты · до 512 МБ</option><option value={5}>5 минут · до 2 ГБ</option><option value={10}>10 минут · до 2 ГБ</option></select></label>
        <p className="text-xs leading-5 text-muted-foreground">При достижении предела запись сохраняется с освобождением ввода. До 20 материалов в этом браузере. Экспортируйте нужные записи перед очисткой данных браузера.</p>
      </aside>
    </div>
    {workspaceMode==='capture'&&<TeachingScenePreview video={video} deviceId={deviceId} ready={ready} controlActive={active(phase)} />}
    </div>
    </div>
    <fieldset hidden={workspaceMode!=='review'} disabled={active(phase)} className="min-w-0 border-0 p-0"><TeachingReview key={storageScope} storageScope={storageScope} selected={clip} refresh={refresh} onSelect={setClip} onBusyChange={setExportBusy} onRouteChange={routeChanged} onClipsChange={clipsChanged} onSourceChange={setRouteSource} visible={workspaceMode==='review'} autoPrepare={autoPrepare?.clip===clip&&autoPrepare.scope===storageScope&&!active(phase)} onAutoPrepareConsumed={consumedAutoPrepare}/></fieldset>
    <p className="flex items-center gap-2 text-xs text-muted-foreground"><Download size={14} />Материал содержит только явно записанный проход. Он ещё не доказывает повторение маршрута ИИ.</p>
  </div>;
}
function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <div className="rounded-xl border border-border bg-muted/30 px-3 py-2.5"><p className="flex items-center gap-2 text-xs text-muted-foreground">{icon}{label}</p><p className="mt-1 text-sm font-medium">{value}</p></div>;
}
