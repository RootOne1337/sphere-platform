'use client';
import { useEffect, useRef, useState } from 'react';
import { Circle, Download, Keyboard, MousePointer2, Square, Video, Wifi } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/lib/store';
import { StreamQualityControl } from './StreamQualityControl';
import { TeachingContacts, stickPoint, type TeachingInput, type TeachingPoint } from './teachingContacts';
import { connectTeaching, type TeachingConnection } from './teachingConnection';
import type { DirectProbeResult } from './directProbe';
import { TeachingReview } from './TeachingReview';

type Phase = 'idle' | 'connecting' | 'preview' | 'opening' | 'arming' | 'recording' | 'stopping' | 'finished';
type Profile = { stick_x: number; stick_y: number; radius: number; action_x: number; action_y: number };
const defaultProfile: Profile = { stick_x: 15, stick_y: 82, radius: 12, action_x: 92, action_y: 88 };
const newId = () => crypto.randomUUID().replaceAll('-', '');
const active = (phase: Phase) => ['opening','arming','recording','stopping'].includes(phase);

export function TeachingWorkbench({ deviceId, readOnly }: { deviceId: string; readOnly: boolean }) {
  const token = useAuthStore(s => s.accessToken), sessionVersion = useAuthStore(s => s.sessionVersion);
  const [phase, setPhase] = useState<Phase>('idle'); const phaseRef = useRef<Phase>('idle');
  const [notice, setNotice] = useState('Подключите прямой поток, проверьте экран и настройте зоны управления.');
  const [native, setNative] = useState('Не открыт'); const [result, setResult] = useState<DirectProbeResult | null>(null);
  const [profile, setProfile] = useState<Profile>(defaultProfile); const profileRef = useRef(profile); profileRef.current = profile;
  const [calibrate, setCalibrate] = useState<'stick' | 'action' | null>(null);
  const [title, setTitle] = useState('Маршрут 01');
  const [progress, setProgress] = useState({ frames: 0, bytes: 0, seconds: 0 });
  const [ready, setReady] = useState(false); const [clip, setClip] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const video = useRef<HTMLVideoElement>(null); const host = useRef<HTMLDivElement>(null);
  const connection = useRef<TeachingConnection | null>(null), controller = useRef<TeachingContacts | null>(null);
  const abort = useRef<AbortController | null>(null), stopPromise = useRef<Promise<void> | null>(null);
  const keys = useRef(new Set<string>()), mouse = useRef<number | null>(null), attached = useRef(false);
  const recordConfig = useRef<Record<string, unknown> | null>(null);
  const finalize = useRef<(() => void) | null>(null);
  const armSent = useRef(false);
  const stopCallback = useRef<(reason?: string) => Promise<void>>(async () => {});
  const change = (value: Phase) => { phaseRef.current = value; setPhase(value); };

  const stop = (reason?: string): Promise<void> => {
    if (stopPromise.current) return stopPromise.current;
    if (!active(phaseRef.current)) return Promise.resolve();
    change('stopping'); keys.current.clear(); mouse.current = null;
    stopPromise.current = (async () => {
      const confirmed = await controller.current?.close() ?? false;
      const conn = connection.current;
      if (conn && armSent.current) {
        await new Promise<void>(resolve => {
          const timeout = setTimeout(() => { finalize.current = null; setNotice('Финализация не подтверждена. Запись не считается завершённой.'); resolve(); }, 10000);
          finalize.current = () => { clearTimeout(timeout); finalize.current = null; resolve(); };
          conn.worker.postMessage({ type: 'stop', confirmed, reason: reason ?? null });
        });
      }
      change('finished'); setReady(false);
      if (reason) setNotice(`Запись остановлена: ${reason}. Проверьте статус сохранённого материала.`);
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
    const blur = () => { if (active(phaseRef.current)) void stopCallback.current('window_focus_lost'); };
    document.addEventListener('visibilitychange', hidden); window.addEventListener('blur', blur);
    return () => {
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
    if (!token || readOnly || phaseRef.current === 'connecting') return;
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
          if (message.type === 'recording') { change('recording'); setNotice('Идёт запись оригинального видео и подтверждённых действий.'); video.current?.focus(); }
          if (message.type === 'progress') setProgress({ frames: Number(message.frames), bytes: Number(message.bytes), seconds: Number(message.seconds) });
          if (message.type === 'failed') { setNotice(`Ошибка записи: ${String(message.reason)}`); void stopCallback.current(String(message.reason)); }
          if (message.type === 'finalized') {
            setClip(typeof message.id === 'string' && /^[0-9a-f]{32}$/.test(message.id) ? message.id : null); setRefresh(v => v + 1);
            const manifest = message.manifest as { complete?: boolean; failure?: string };
            setNotice(manifest.complete ? 'Материал сохранён. Видео и журнал готовы к просмотру.' : `Материал неполный: ${manifest.failure ?? 'нет подтверждения'}. Для повторения маршрута не допущен.`);
            finalize.current?.();
          }
        });
      if (request.signal.aborted) { conn.close(); conn.worker.terminate(); return; }
      connection.current = conn; change('preview');
      setNotice('Проверьте игру в потоке. Нажмите «Центр стика» и «Кнопка действия», затем укажите их на экране.');
    } catch (error) { request.abort(); change('idle'); setNotice(`Подключение не готово: ${error instanceof Error ? error.message : 'ошибка'}`); }
  };
  const record = async () => {
    const conn = connection.current, binding = conn?.binding(), endpoint = conn?.endpoint();
    if (readOnly || phaseRef.current !== 'preview' || !conn?.fresh() || !binding || !endpoint || !attached.current) return;
    change('opening');
    let storage: StorageEstimate;
    try { storage = await navigator.storage.estimate(); } catch { change('preview'); setNotice('Не удалось проверить квоту браузера.'); return; }
    if ((phaseRef.current as Phase) !== 'opening' || connection.current !== conn) return;
    if ((storage.quota ?? 0) - (storage.usage ?? 0) < 600 * 1024 * 1024) { change('preview'); setNotice('Нужно не менее 600 МБ свободной квоты браузера для записи. Экспортируйте и удалите старые материалы.'); return; }
    const p = profileRef.current, radius = p.radius / 100 * Math.min(binding.width, binding.height);
    const cx = p.stick_x / 100 * binding.width, cy = p.stick_y / 100 * binding.height;
    if (cx - radius < 0 || cy - radius < 0 || cx + radius >= binding.width || cy + radius >= binding.height) {
      change('preview'); setNotice('Зона стика выходит за экран. Уменьшите радиус или измените центр.'); return;
    }
    const id = newId(); setProgress({ frames: 0, bytes: 0, seconds: 0 }); stopPromise.current = null;
    recordConfig.current = { id, device_id: deviceId, width: binding.width, height: binding.height,
      capture_epoch: binding.captureEpoch, title: title.trim().slice(0,128) || 'Маршрут', profile: p,
      source: 'direct_webrtc_h264', target_fps: 60, actual_fps_unverified: true };
    change('opening'); setNotice('Открываем три контакта. Требуется APK 1.2.89 или новее с contact_protocol=1.');
    try {
      controller.current = new TeachingContacts(endpoint, binding, conn.fresh,
        (event: TeachingInput) => conn.worker.postMessage({ type: 'input', event }), (state, reason) => {
          setNative(state === 'ready' ? 'READY · 3 контакта' : state === 'closed' ? 'CLOSED · освобождено' : state);
          if (state === 'ready' && phaseRef.current === 'opening') {
            change('arming'); armSent.current = true; conn.worker.postMessage({ type: 'arm', config: recordConfig.current });
            setNotice('Ждём ключевой H264-кадр с заголовками. Управление включится после начала записи.');
            setTimeout(() => { if (phaseRef.current === 'arming') void stopCallback.current('keyframe_start_timeout'); }, 12000);
          }
          if (state === 'failed') void stopCallback.current(reason ?? 'native_input_failed');
        });
    } catch { void stop('contact_protocol_unavailable'); }
  };
  const updateStick = () => {
    const binding = connection.current?.binding(); if (!binding) return;
    const p = profileRef.current;
    const center = { x: Math.round(p.stick_x * binding.width / 100), y: Math.round(p.stick_y * binding.height / 100) };
    const target = stickPoint(keys.current, center, p.radius * Math.min(binding.width,binding.height) / 100,
      keys.current.has('ShiftLeft') || keys.current.has('ShiftRight'));
    // A floating joystick takes its origin from DOWN. Establish the centre once,
    // then retain the same contact while changing direction/speed with MOVE.
    if (target && !controller.current?.hasContact(0)) controller.current?.set(0, center);
    controller.current?.set(0, target);
  };
  const key = (event: React.KeyboardEvent, down: boolean) => {
    if (event.code === 'Escape') { event.preventDefault(); void stop(); return; }
    if (phaseRef.current !== 'recording' || !['KeyW','KeyA','KeyS','KeyD','Space','ShiftLeft','ShiftRight'].includes(event.code)) return;
    event.preventDefault(); if (event.repeat || keys.current.has(event.code) === down) return;
    if (down) keys.current.add(event.code); else keys.current.delete(event.code);
    if (event.code === 'Space') {
      const b = connection.current?.binding(), p = profileRef.current;
      if (b) controller.current?.set(2, down ? { x: Math.round(p.action_x * (b.width-1) / 100), y: Math.round(p.action_y * (b.height-1) / 100) } : null);
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
  return <div ref={host} className="space-y-4" aria-label="Запись учебного маршрута">
    <section className="rounded-2xl border border-border bg-card p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest text-primary">Обучение маршруту</p><h2 className="mt-1 text-xl font-semibold">Покажите путь один раз</h2><p className="mt-2 max-w-3xl text-sm text-muted-foreground">Оригинальное H264-видео, устойчивые удержания и подтверждения Android в одном материале. Автономное повторение и 3D-реконструкция подключаются отдельным этапом.</p></div><StreamQualityControl deviceId={deviceId} readOnly={readOnly || active(phase)} /></div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3"><Metric icon={<Wifi size={15} />} label="Транспорт" value={result ? `${result.path} · ${result.state}` : 'Не подключён'} /><Metric icon={<Keyboard size={15} />} label="Нативный ввод" value={native} /><Metric icon={<Video size={15} />} label="Записано" value={`${progress.seconds.toFixed(1)} с · ${progress.frames} кадров · ${(progress.bytes/1048576).toFixed(1)} МБ`} /></div>
    </section>
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
      <section className="overflow-hidden rounded-2xl border border-border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3 text-sm"><span className="font-medium">{phase === 'recording' ? '● Запись' : 'Прямой экран Android'}</span><span className="text-xs text-muted-foreground">{connection.current?.binding() ? `${connection.current.binding()!.width} × ${connection.current.binding()!.height}` : 'Размер ожидается'}</span></div>
        <video ref={video} muted playsInline tabIndex={0} aria-label="Игровой экран: WASD, мышь, пробел, Shift; Escape — остановить запись"
          className="aspect-video max-h-[70dvh] w-full touch-none bg-black object-contain outline-none focus-visible:ring-2 focus-visible:ring-primary"
          onKeyDown={e => key(e,true)} onKeyUp={e => key(e,false)} onContextMenu={e => e.preventDefault()}
          onBlur={() => { if (keys.current.size || mouse.current !== null) void stop('input_focus_lost'); }}
          onPointerDown={e => {
            const pos = point(e), b = connection.current?.binding(); if (!pos || !b) return;
            if (calibrate && !active(phase)) {
              setProfile(p => calibrate === 'stick' ? { ...p, stick_x: pos.x/b.width*100, stick_y: pos.y/b.height*100 }
                : { ...p, action_x: pos.x/b.width*100, action_y: pos.y/b.height*100 }); setCalibrate(null); return;
            }
            if (phase !== 'recording' || mouse.current !== null || e.button !== 0) return;
            e.preventDefault(); e.currentTarget.focus(); e.currentTarget.setPointerCapture(e.pointerId);
            mouse.current = e.pointerId; controller.current?.set(1,pos);
          }}
          onPointerMove={e => { if (mouse.current === e.pointerId) { const p = point(e); if(p) controller.current?.set(1,p); } }}
          onPointerUp={e => { if (mouse.current === e.pointerId) { mouse.current = null; controller.current?.set(1,null); e.currentTarget.releasePointerCapture(e.pointerId); } }}
          onPointerCancel={() => { void stop('pointer_cancelled'); }}
          onLostPointerCapture={e => { if (mouse.current === e.pointerId) void stop('pointer_capture_lost'); }} />
        <div className="flex flex-wrap gap-2 border-t border-border p-3 text-xs text-muted-foreground"><span className="rounded-md bg-muted px-2 py-1">WASD · стик</span><span className="rounded-md bg-muted px-2 py-1">Shift · 40% скорости</span><span className="rounded-md bg-muted px-2 py-1">ЛКМ + движение · камера</span><span className="rounded-md bg-muted px-2 py-1">Пробел · удержание кнопки</span></div>
      </section>
      <aside className="space-y-4 rounded-2xl border border-border bg-card p-4">
        <h3 className="font-semibold">Подготовка маршрута</h3>
        <label className="block space-y-1 text-sm"><span>Название</span><input className={field} value={title} maxLength={128} disabled={active(phase)} onChange={e => setTitle(e.target.value)} /></label>
        <div className="space-y-2"><p className="text-sm font-medium">Калибровка касаний</p><Button variant="outline" className="w-full justify-start" disabled={!ready || active(phase)} onClick={() => setCalibrate('stick')}><MousePointer2 size={15} className="mr-2" />Центр стика · {profile.stick_x.toFixed(1)} / {profile.stick_y.toFixed(1)}%</Button><Button variant="outline" className="w-full justify-start" disabled={!ready || active(phase)} onClick={() => setCalibrate('action')}>Кнопка действия · {profile.action_x.toFixed(1)} / {profile.action_y.toFixed(1)}%</Button>{calibrate && <p role="status" className="text-xs text-primary">Укажите {calibrate === 'stick' ? 'центр стика' : 'кнопку действия'} на экране. Касание в игру не отправляется.</p>}
          <label className="block space-y-1 text-sm"><span>Радиус стика · % короткой стороны</span><input className={field} type="number" min={1} max={20} step={0.5} value={profile.radius} disabled={active(phase)} onChange={e => { const n = Number(e.target.value); if(n>=1&&n<=20) setProfile(p => ({...p,radius:n})); }} /></label>
        </div>
        <p className="text-xs leading-5 text-muted-foreground">Перед качественным проходом: 1920 × 1080, DPI 320, рендер игры 100%, цель 60 FPS. Кнопка «Качество» задаёт предел кодека; фактическую частоту проверяем по записи.</p>
        <p className="text-xs leading-5 text-muted-foreground">До 2 минут / 512 МБ на материал, до 20 материалов. Файлы хранятся в этом браузере, автоматически на сервер не отправляются. Экспортируйте нужные записи перед очисткой данных браузера.</p>
      </aside>
    </div>
    <div className="sticky bottom-3 z-20 flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-card/95 p-3 shadow-xl backdrop-blur">
      <Button variant="outline" disabled={readOnly || active(phase) || phase === 'connecting'} onClick={() => { void connect(); }}>{phase === 'idle' ? 'Подключить поток' : 'Подключить заново'}</Button>
      <Button disabled={readOnly || phase !== 'preview' || !ready || !!calibrate} onClick={() => { void record(); }}><Circle size={15} className="mr-2 text-red-500" />Записать маршрут</Button>
      <Button variant="destructive" disabled={!active(phase) || phase === 'stopping'} onClick={() => { void stop(); }}><Square size={15} className="mr-2" />{phase === 'stopping' ? 'Освобождение и сохранение…' : 'Остановить · Esc'}</Button>
      <p role="status" className="min-w-[220px] flex-1 text-xs leading-5 text-muted-foreground">{readOnly ? 'Для записи требуется право stream:control.' : notice}</p>
    </div>
    <TeachingReview selected={clip} refresh={refresh} onSelect={setClip} />
    <p className="flex items-center gap-2 text-xs text-muted-foreground"><Download size={14} />Материал содержит только явно записанный проход. Он ещё не доказывает повторение маршрута ИИ.</p>
  </div>;
}
function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <div className="rounded-xl border border-border bg-muted/30 px-3 py-2.5"><p className="flex items-center gap-2 text-xs text-muted-foreground">{icon}{label}</p><p className="mt-1 text-sm font-medium">{value}</p></div>;
}
