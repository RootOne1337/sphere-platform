'use client';
import { useEffect, useRef, useState } from 'react';
import { Circle, Download, Keyboard, MousePointer2, Square, Video, Wifi } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/lib/store';
import { StreamQualityControl } from './StreamQualityControl';
import { TeachingContacts, type TeachingInput, type TeachingPoint } from './teachingContacts';
import { calibrated, calibrateProfile, calibrationNames, cameraContact, defaultTeachingProfile, fromPercent, movementTargets, profileIssue, vehicleButtons, type CalibrationTarget, type TeachingProfile } from './teachingKeymap';
import { connectTeaching, type TeachingConnection } from './teachingConnection';
import type { DirectProbeResult } from './directProbe';
import { TeachingReview } from './TeachingReview';
import { TeachingScenePreview } from './TeachingScenePreview';

type Phase = 'idle' | 'connecting' | 'preview' | 'opening' | 'controlling' | 'arming' | 'recording' | 'stopping' | 'finished';
const newId = () => crypto.randomUUID().replaceAll('-', '');
const active = (phase: Phase) => ['opening','controlling','arming','recording','stopping'].includes(phase);
const inputEnabled = (phase: Phase) => phase === 'controlling' || phase === 'recording';
const stopReasons: Record<string,string> = { page_hidden: 'страница скрыта', window_focus_lost: 'окно потеряло фокус', input_focus_lost: 'фокус управления потерян при удержании', connection_closed: 'соединение закрыто', video_stalled: 'нет свежих кадров', pointer_cancelled: 'касание отменено', keyframe_start_timeout: 'ключевой кадр не получен за 12 секунд' };
Object.assign(stopReasons,{contact_video_stale:'ввод остановлен: видеокадр старше 250 мс',contact_channel_closed:'канал ввода закрыт',contact_ack_timeout:'Android не подтвердил команду за 500 мс',contact_ready_timeout:'Android не подтвердил готовность ввода за 6 секунд'});
stopReasons.native_closed_unexpectedly='Android завершил сеанс ввода. Управление выключено';

export function TeachingWorkbench({ deviceId, readOnly }: { deviceId: string; readOnly: boolean }) {
  const token = useAuthStore(s => s.accessToken), sessionVersion = useAuthStore(s => s.sessionVersion);
  const user = useAuthStore(s => s.user);
  const [storageScope, setStorageScope] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('idle'); const phaseRef = useRef<Phase>('idle');
  const [notice, setNotice] = useState('Подключите прямой поток, проверьте экран и настройте зоны управления.');
  const [native, setNative] = useState('Не открыт'); const [result, setResult] = useState<DirectProbeResult | null>(null);
  const [profile, setProfile] = useState<TeachingProfile>(defaultTeachingProfile); const profileRef = useRef(profile); profileRef.current = profile;
  const [calibrate, setCalibrate] = useState<CalibrationTarget | null>(null);
  const [hudHidden, setHudHidden] = useState(false);
  const [exportBusy,setExportBusy] = useState(false);
  const [title, setTitle] = useState('Маршрут 01');
  const [minutes, setMinutes] = useState(10);
  const [progress, setProgress] = useState({ frames: 0, bytes: 0, seconds: 0 });
  const [encoded, setEncoded] = useState('Encoded-приём ожидается');
  const [ready, setReady] = useState(false); const [clip, setClip] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const video = useRef<HTMLVideoElement>(null); const host = useRef<HTMLDivElement>(null);
  const connection = useRef<TeachingConnection | null>(null), controller = useRef<TeachingContacts | null>(null);
  const abort = useRef<AbortController | null>(null), stopPromise = useRef<Promise<void> | null>(null);
  const keys = useRef(new Set<string>()), mouse = useRef<number | null>(null), attached = useRef(false);
  const mouseContact = useRef<1|2>(1);
  const recordConfig = useRef<Record<string, unknown> | null>(null);
  const finalize = useRef<(() => void) | null>(null);
  const armSent = useRef(false);
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
    controller.current = null; attached.current = false; armSent.current = false; setReady(false); change('idle');
  };
  useEffect(() => {
    const timer = setInterval(() => setReady(connection.current?.fresh() === true && attached.current), 200);
    const hidden = () => { if (document.hidden) void stopCallback.current('page_hidden'); };
    const blur = () => {
      if(!active(phaseRef.current))return;
      if(keys.current.size || mouse.current !== null) { void stopCallback.current('window_focus_lost'); return; }
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
    await disconnect(); stopPromise.current = null; setClip(null); setResult(null); change('connecting');
    setNative('Не открыт'); setNotice('Подключаем один прямой поток. Ввод ещё выключен.');
    const request = new AbortController(); abort.current = request;
    try {
      const conn = await connectTeaching(deviceId, token, video.current!, request.signal, setResult,
        reason => { if (request.signal.aborted) return; setNotice(`Транспорт остановлен: ${reason}`); void stopCallback.current(reason).then(() => {
          connection.current?.close(); if (!active(phaseRef.current)) setReady(false);
        }); }, message => {
          if (request.signal.aborted) return;
          if (message.type === 'attached') attached.current = true;
          if (message.type === 'recording') { change('recording'); setNotice('Идёт запись оригинального видео и подтверждённых действий.'); video.current?.focus({preventScroll:true}); }
          if (message.type === 'progress') setProgress({ frames: Number(message.frames), bytes: Number(message.bytes), seconds: Number(message.seconds) });
          if (message.type === 'limit_reached') { setNotice('Достигнут выбранный предел. Освобождаем ввод и сохраняем запись.'); void stopCallback.current(); }
          if (message.type === 'encoded_status') setEncoded(`Encoded ${Number(message.frames)} · ${String(message.kind)} · NAL ${Array.isArray(message.nal_types) ? message.nal_types.join('/') : '?'} · ${String(message.width)}×${String(message.height)}`);
          if (message.type === 'failed') { setNotice(`Ошибка записи: ${String(message.reason)}`); void stopCallback.current(String(message.reason)); }
          if (message.type === 'finalized') {
            setClip(typeof message.id === 'string' && /^[0-9a-f]{32}$/.test(message.id) ? message.id : null); setRefresh(v => v + 1);
            const manifest = message.manifest as { complete?: boolean; failure?: string; frames?: number; media_duration_ticks_90k?: number; files?: Record<string,{bytes:number}> };
            if(typeof manifest.frames === 'number')setProgress({ frames: manifest.frames, bytes: manifest.files?.['video.h264']?.bytes ?? 0, seconds: (manifest.media_duration_ticks_90k ?? 0)/90000 });
            setNotice(manifest.complete ? 'Материал сохранён. Видео и журнал готовы к просмотру.' : `Материал неполный: ${manifest.failure ?? 'нет подтверждения'}. Для повторения маршрута не допущен.`);
            finalize.current?.();
          }
        });
      if (request.signal.aborted) { conn.close(); conn.worker.terminate(); return; }
      connection.current = conn; change('preview');
      setNotice('Проверьте игру в потоке. Нажмите «Центр стика» и «Кнопка действия», затем укажите их на экране.');
    } catch (error) { request.abort(); change('idle'); setNotice(`Подключение не готово: ${error instanceof Error ? error.message : 'ошибка'}`); }
  };
  const openInput = (mode: 'control' | 'record', conn: TeachingConnection) => {
    const binding = conn.binding(), endpoint = conn.endpoint();
    const generation=ownerGeneration.current;
    if(!binding || !endpoint)throw Error('Ввод ещё не готов');
    controller.current = new TeachingContacts(endpoint, binding, conn.fresh,
      (event: TeachingInput) => { if(armSent.current)conn.worker.postMessage({ type: 'input', event }); }, (state, reason) => {
        if(generation!==ownerGeneration.current || connection.current!==conn)return;
        setNative(state === 'ready' ? 'READY · 3 контакта' : state === 'closed' ? 'CLOSED · освобождено' : state);
        if (state === 'ready' && phaseRef.current === 'opening') {
          if(mode === 'control') { change('controlling'); setNotice('Управление включено без записи. Щёлкните по экрану: WASD, мышь, пробел.'); video.current?.focus({preventScroll:true}); }
          else {
            change('arming'); armSent.current = true; conn.worker.postMessage({ type: 'arm', config: recordConfig.current });
            setNotice('Ждём ключевой H264-кадр. Не удерживайте клавиши до начала записи.');
            setTimeout(() => { if (phaseRef.current === 'arming') void stopCallback.current('keyframe_start_timeout'); }, 12000);
          }
        }
        if (state === 'failed') void stopCallback.current(reason ?? 'native_input_failed');
        if (state === 'closed' && active(phaseRef.current) && phaseRef.current!=='stopping' && !expectedOwnerClose.current) void stopCallback.current('native_closed_unexpectedly');
      });
  };
  const enableControl = () => {
    const conn = connection.current;
    if(readOnly || phaseRef.current !== 'preview' || !conn?.fresh() || !attached.current || calibrate)return;
    const binding=conn.binding();if(!binding)return;
    const issue=profileIssue(profileRef.current,binding);if(issue){setNotice(issue);return;}
    stopPromise.current = null; change('opening');
    try { openInput('control',conn); } catch { void stop('contact_protocol_unavailable'); }
  };
  const record = async () => {
    const conn = connection.current, binding = conn?.binding(), endpoint = conn?.endpoint();
    if (readOnly || !storageScope || !['preview','controlling'].includes(phaseRef.current) || !conn?.fresh() || !binding || !endpoint || !attached.current) return;
    if(phaseRef.current === 'controlling') {
      if(keys.current.size || mouse.current !== null || !controller.current?.isNeutral) { setNotice('Отпустите клавиши и мышь перед началом записи.'); return; }
      change('opening');expectedOwnerClose.current=true; const closed = await controller.current.close();expectedOwnerClose.current=false;
      if((phaseRef.current as Phase) !== 'opening' || connection.current !== conn)return;
      if(!closed){change('finished');setNotice('Освобождение прежнего ввода не подтверждено. Подключите поток заново.');return;}
      controller.current = null;
    }
    change('opening');
    let storage: StorageEstimate;
    try { storage = await navigator.storage.estimate(); } catch { change('preview'); setNotice('Не удалось проверить квоту браузера.'); return; }
    if ((phaseRef.current as Phase) !== 'opening' || connection.current !== conn) return;
    const maxBytes = minutes === 2 ? 512*1024*1024 : 2*1024*1024*1024;
    if ((storage.quota ?? 0) - (storage.usage ?? 0) < maxBytes + 100*1024*1024) { change('preview'); setNotice(`Нужно ${minutes === 2 ? '612 МБ' : '2,1 ГБ'} свободной квоты браузера. Выберите меньший предел или экспортируйте старые материалы.`); return; }
    const p = profileRef.current, issue=profileIssue(p,binding);
    if(issue){change('preview');setNotice(issue);return;}
    const id = newId(); setProgress({ frames: 0, bytes: 0, seconds: 0 }); stopPromise.current = null;
    recordConfig.current = { id, storage_scope: storageScope, device_id: deviceId, width: binding.width, height: binding.height,
      capture_epoch: binding.captureEpoch, title: title.trim().slice(0,128) || 'Маршрут', profile: p,
      source: 'direct_webrtc_h264', target_fps: 60, actual_fps_unverified: true,
      hud_hidden_declared: hudHidden, contact_roles: p.mode==='stick'?['stick','camera','action']:['throttle_or_brake','steering','camera_or_action'],
      max_duration_ms: minutes*60000, max_bytes: maxBytes, max_frames: minutes*3600 };
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
    if (!inputEnabled(phaseRef.current) || !['KeyW','KeyA','KeyS','KeyD','Space','ShiftLeft','ShiftRight'].includes(event.code)) return;
    event.preventDefault(); if (event.repeat || keys.current.has(event.code) === down) return;
    const binding=connection.current?.binding(), mapping=profileRef.current;
    if(event.code==='Space'&&down&&mapping.mode==='vehicle_buttons') {
      if(mouse.current!==null){setNotice('Отпустите мышь, чтобы использовать дополнительное действие.');return;}
      if(!binding||!calibrated(mapping,binding,'action')){setNotice('Сначала укажите дополнительную кнопку транспорта для пробела.');return;}
    }
    if (down) keys.current.add(event.code); else keys.current.delete(event.code);
    if (event.code === 'Space') {
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
  const binding=connection.current?.binding(), mappingIssue=binding?profileIssue(profile,binding):null;
  const calibrationMarkers=binding?(profile.mode==='vehicle_buttons'
    ?vehicleButtons.filter(target=>calibrated(profile,binding,target)).map(target=>({...fromPercent(profile.vehicle[target],binding),label:({forward:'W',reverse:'S',left:'A',right:'D'})[target]}))
    :calibrated(profile,binding,'stick')?[{...fromPercent({x:profile.stick_x,y:profile.stick_y},binding),label:'WASD'}]:[]):[];
  if(binding&&calibrated(profile,binding,'action'))calibrationMarkers.push({...fromPercent({x:profile.action_x,y:profile.action_y},binding),label:'Space'});
  const chooseCalibration=(target:CalibrationTarget)=>{setCalibrate(target);video.current?.scrollIntoView({block:'center',behavior:'smooth'});};
  return <div ref={host} className="space-y-4" aria-label="Запись учебного маршрута">
    <div aria-label="Панель записи" className="sticky top-16 z-30 flex flex-wrap items-center gap-2 rounded-2xl border border-border bg-card/95 p-3 shadow-xl backdrop-blur">
      <Button variant="outline" disabled={readOnly || exportBusy || !storageScope || active(phase) || phase === 'connecting'} onClick={() => { void connect(); }}>{phase === 'idle' ? 'Подключить поток' : 'Подключить заново'}</Button>
      <Button variant="outline" disabled={readOnly || exportBusy || phase !== 'preview' || !ready || !!calibrate || !!mappingIssue} onClick={enableControl}><Keyboard size={15} className="mr-2" />Включить управление</Button>
      <Button disabled={readOnly || exportBusy || !['preview','controlling'].includes(phase) || !ready || !!calibrate || !!mappingIssue} onClick={() => { void record(); }}><Circle size={15} className="mr-2 text-red-500" />Записать маршрут</Button>
      <Button variant="destructive" disabled={!active(phase) || phase === 'stopping'} onClick={() => { void stop(); }}><Square size={15} className="mr-2" />{phase === 'stopping' ? 'Освобождение и сохранение…' : 'Остановить · Esc'}</Button>
      {(phase==='recording'||phase==='finished')&&<span className="rounded-lg bg-muted px-2 py-1 font-mono text-xs tabular-nums">{progress.seconds.toFixed(1)} с · {progress.frames} кадров{progress.seconds>0?` · ${(progress.frames/progress.seconds).toFixed(1)} средних FPS`:''}</span>}
      <p role="status" className="min-w-[220px] flex-1 text-xs leading-5 text-muted-foreground">{readOnly ? 'Для записи требуется право stream:control.' : exportBusy?'Обрабатываем сохранённый материал. Дождитесь завершения перед новым управлением.':calibrate ? `Укажите ${calibrationNames[calibrate]} на экране. Касание в игру не отправляется.` : mappingIssue ?? notice}</p>
    </div>
    <section className="rounded-2xl border border-border bg-card p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest text-primary">Обучение маршруту</p><h2 className="mt-1 text-xl font-semibold">Покажите путь один раз</h2><p className="mt-2 max-w-3xl text-sm text-muted-foreground">Подготовьте игру с клавиатуры, включите запись и покажите маршрут. Видео и подтверждённые касания сохраняются вместе; локальный 3D-просмотр помогает оценить геометрию.</p></div><StreamQualityControl deviceId={deviceId} readOnly={readOnly || active(phase)} /></div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3"><Metric icon={<Wifi size={15} />} label="Транспорт" value={result ? `${result.path} · ${result.state}` : 'Не подключён'} /><Metric icon={<Keyboard size={15} />} label="Нативный ввод" value={native} /><Metric icon={<Video size={15} />} label="Записано" value={`${progress.seconds.toFixed(1)} с · ${progress.frames} кадров · ${(progress.bytes/1048576).toFixed(1)} МБ`} /></div>
    </section>
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
      <section className="overflow-hidden rounded-2xl border border-border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3 text-sm"><span className="font-medium">{phase === 'recording' ? '● Запись' : 'Прямой экран Android'}</span><span className="text-xs text-muted-foreground">{connection.current?.binding() ? `${connection.current.binding()!.width} × ${connection.current.binding()!.height}` : 'Размер ожидается'}</span></div>
        <div className="relative">
        <video ref={video} muted playsInline tabIndex={0} aria-label="Игровой экран: WASD, мышь, пробел, Shift; Escape — остановить запись"
          className="aspect-video max-h-[calc(100dvh-14rem)] w-full scroll-mt-56 touch-none bg-black object-contain outline-none focus-visible:ring-2 focus-visible:ring-primary"
          onKeyDown={e => key(e,true)} onKeyUp={e => key(e,false)} onContextMenu={e => e.preventDefault()}
          onBlur={() => { if (keys.current.size || mouse.current !== null) void stop('input_focus_lost'); }}
          onPointerDown={e => {
            const pos = point(e), b = connection.current?.binding(); if (!pos || !b) return;
            if (calibrate && !active(phase)) {
              setProfile(p => calibrateProfile(p,b,calibrate,pos)); setCalibrate(null); return;
            }
            if (!inputEnabled(phaseRef.current) || mouse.current !== null || e.button !== 0) return;
            if(profileRef.current.mode==='vehicle_buttons'&&keys.current.has('Space')){setNotice('Отпустите пробел, чтобы двигать камеру мышью.');return;}
            e.preventDefault(); e.currentTarget.focus(); e.currentTarget.setPointerCapture(e.pointerId);
            mouse.current = e.pointerId; mouseContact.current=cameraContact(profileRef.current);controller.current?.set(mouseContact.current,pos);
          }}
          onPointerMove={e => { if (mouse.current === e.pointerId) { const p = point(e); if(p) controller.current?.set(mouseContact.current,p); } }}
          onPointerUp={e => { if (mouse.current === e.pointerId) { mouse.current = null; controller.current?.set(mouseContact.current,null); e.currentTarget.releasePointerCapture(e.pointerId); } }}
          onPointerCancel={() => { void stop('pointer_cancelled'); }}
          onLostPointerCapture={e => { if (mouse.current === e.pointerId) void stop('pointer_capture_lost'); }} />
        {ready&&!active(phase)&&binding&&<svg aria-label="Проверенные точки управления" className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${binding.width} ${binding.height}`} preserveAspectRatio="xMidYMid meet">
          {calibrationMarkers.map(marker=><g key={marker.label} transform={`translate(${marker.x} ${marker.y})`}><circle r={Math.max(9,binding.height*.018)} fill="#020617cc" stroke="#38bdf8" strokeWidth={2}/><text textAnchor="middle" dominantBaseline="central" fill="white" fontSize={Math.max(9,binding.height*.018)}>{marker.label}</text></g>)}
        </svg>}
        {calibrate&&<p className="pointer-events-none absolute left-2 right-2 top-2 rounded-lg bg-background/95 px-3 py-2 text-sm text-primary">Укажите {calibrationNames[calibrate]}. Это только калибровка.</p>}
        </div>
        <div className="flex flex-wrap gap-2 border-t border-border p-3 text-xs text-muted-foreground"><span className={`rounded-md px-2 py-1 ${inputEnabled(phase) ? 'bg-primary/15 text-primary' : 'bg-muted'}`}>{inputEnabled(phase) ? 'Управление включено · фокус на экране' : 'Управление выключено'}</span><span className="rounded-md bg-muted px-2 py-1">{profile.mode==='stick'?'WASD · стик':'W/S · газ и тормоз · A/D · руль'}</span>{profile.mode==='stick'&&<span className="rounded-md bg-muted px-2 py-1">Shift · 40% скорости</span>}<span className="rounded-md bg-muted px-2 py-1">ЛКМ + движение · камера</span><span className="rounded-md bg-muted px-2 py-1">Пробел · удержание кнопки</span></div>
        <details className="px-4 pb-3 text-xs text-muted-foreground"><summary>Диагностика приёма видео</summary>{encoded}</details>
      </section>
      <aside className="space-y-4 rounded-2xl border border-border bg-card p-4">
        <h3 className="font-semibold">Подготовка маршрута</h3>
        <label className="block space-y-1 text-sm"><span>Название</span><input className={field} value={title} maxLength={128} disabled={active(phase)} onChange={e => setTitle(e.target.value)} /></label>
        <label className="block space-y-1 text-sm"><span>Схема управления</span><select className={field} value={profile.mode} disabled={active(phase)} onChange={e=>{setCalibrate(null);setProfile(p=>({...p,mode:e.target.value as TeachingProfile['mode']}));}}><option value="stick">Стик · ходьба / аналоговое управление</option><option value="vehicle_buttons">Транспорт · газ, тормоз, левый и правый руль</option></select></label>
        <div className="space-y-2"><p className="text-sm font-medium">Калибровка касаний</p>
          {profile.mode==='stick'?<><Button variant="outline" className="w-full justify-start" disabled={!ready || active(phase)} onClick={() => chooseCalibration('stick')}><MousePointer2 size={15} className="mr-2" />Центр стика · {profile.stick_x.toFixed(1)} / {profile.stick_y.toFixed(1)}%</Button>
            <label className="block space-y-1 text-sm"><span>Радиус стика · % короткой стороны</span><input className={field} type="number" min={1} max={20} step={0.5} value={profile.radius} disabled={active(phase)} onChange={e => { const n = Number(e.target.value); if(n>=1&&n<=20) setProfile(p => ({...p,radius:n})); }} /></label></>
            :<>{vehicleButtons.map(target=><Button key={target} variant="outline" className="w-full justify-start" disabled={!ready||active(phase)} onClick={()=>chooseCalibration(target)}>{calibrationNames[target]} · {profile.vehicle[target].x.toFixed(1)} / {profile.vehicle[target].y.toFixed(1)}% {binding&&calibrated(profile,binding,target)?'✓':'· указать'}</Button>)}
              <p className="text-xs leading-5 text-muted-foreground">Сначала сядьте в транспорт и укажите четыре экранные кнопки. Координаты-примеры не включают управление. W/S — газ/тормоз, A/D — поворот; мышь и пробел используются по очереди.</p></>}
          <Button variant="outline" className="w-full justify-start" disabled={!ready || active(phase)} onClick={() => chooseCalibration('action')}>{profile.mode==='vehicle_buttons'?'Доп. действие · пробел':'Кнопка действия'} · {profile.action_x.toFixed(1)} / {profile.action_y.toFixed(1)}%</Button>
          {calibrate&&<Button size="sm" variant="ghost" onClick={()=>setCalibrate(null)}>Отменить калибровку</Button>}
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={hudHidden} disabled={active(phase)} onChange={e=>setHudHidden(e.target.checked)} />HUD скрыт в игре</label>
        <p className="text-xs leading-5 text-muted-foreground">Кнопки калибруйте до отключения HUD. Флажок сохраняет пометку в материале; он не скрывает интерфейс игры и не вырезает надписи из видео.</p>
        <p className="text-xs leading-5 text-muted-foreground">Перед качественным проходом: 1920 × 1080, DPI 320, рендер игры 100%, цель 60 FPS. Кнопка «Качество» задаёт предел кодека; фактическую частоту проверяем по записи.</p>
        <label className="block space-y-1 text-sm"><span>Предел записи</span><select className={field} value={minutes} disabled={active(phase)} onChange={e=>setMinutes(Number(e.target.value))}><option value={2}>2 минуты · до 512 МБ</option><option value={5}>5 минут · до 2 ГБ</option><option value={10}>10 минут · до 2 ГБ</option></select></label>
        <p className="text-xs leading-5 text-muted-foreground">При достижении предела запись сохраняется с освобождением ввода. До 20 материалов в этом браузере. Экспортируйте нужные записи перед очисткой данных браузера.</p>
      </aside>
    </div>
    <TeachingScenePreview video={video} deviceId={deviceId} ready={ready} controlActive={active(phase)} />
    <fieldset disabled={active(phase)} className="min-w-0 border-0 p-0"><TeachingReview key={storageScope} storageScope={storageScope} selected={clip} refresh={refresh} onSelect={setClip} onBusyChange={setExportBusy} /></fieldset>
    <p className="flex items-center gap-2 text-xs text-muted-foreground"><Download size={14} />Материал содержит только явно записанный проход. Он ещё не доказывает повторение маршрута ИИ.</p>
  </div>;
}
function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <div className="rounded-xl border border-border bg-muted/30 px-3 py-2.5"><p className="flex items-center gap-2 text-xs text-muted-foreground">{icon}{label}</p><p className="mt-1 text-sm font-medium">{value}</p></div>;
}
