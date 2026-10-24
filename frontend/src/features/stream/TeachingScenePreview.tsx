'use client';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { Box, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';

const service = 'http://127.0.0.1:3332';
// A different local site lets Chromium isolate the heavy viewer renderer from
// the direct-input page. Ports alone are different origins, but the same site.
const viewer = 'http://localhost:3331/?url=rerun%2Bhttp%3A%2F%2F127.0.0.1%3A3330%2Fproxy';
type Session = { id: string; key: string };
type Report = { windows: number; points: number; inference_ms: number; frame_sequence: number; state: string };

/** Local master preview only. No Android input authority, frame archive or motor queue. */
export function TeachingScenePreview({ video, deviceId, ready, controlActive }: { video: RefObject<HTMLVideoElement | null>; deviceId: string; ready: boolean; controlActive: boolean }) {
  const [running,setRunning] = useState(false), [status,setStatus] = useState('Запустите локальный обработчик и подключите 3D-просмотр.');
  const [report,setReport] = useState<Report | null>(null), [local,setLocal] = useState(false);
  const session = useRef<Session | null>(null), generation = useRef(0);
  useEffect(()=>{setLocal(['127.0.0.1','localhost','[::1]'].includes(window.location.hostname));},[]);
  useEffect(()=>{
    if(!running)return;
    let disposed = false, timer: ReturnType<typeof setTimeout> | undefined, frameCallback: number | undefined;
    let lastFrameAt = 0, sequence = 0, used = -1;
    const current = ++generation.current, request = new AbortController();
    const element = video.current, canvas = document.createElement('canvas');
    const observe = () => {
      if(disposed || !element)return;
      frameCallback = element.requestVideoFrameCallback(()=>{lastFrameAt=performance.now();sequence++;observe();});
    };
    const headers = () => ({ 'X-Sphere-Preview': '1', 'X-Scene-Session': session.current?.id ?? '', 'X-Scene-Key': session.current?.key ?? '' });
    const tick = async () => {
      if(disposed || !element)return;
      try {
        if(document.hidden || !element.videoWidth || element.readyState < 2 || performance.now()-lastFrameAt > 500 || sequence === used) {
          setStatus('Ожидание нового кадра прямого потока.');
        } else {
          // One request at a time; sampling never builds a backlog. The original H264 recording is independent.
          used = sequence;
          const width = Math.min(560,element.videoWidth); canvas.width=width;canvas.height=Math.max(1,Math.round(width*element.videoHeight/element.videoWidth));
          canvas.getContext('2d')!.drawImage(element,0,0,canvas.width,canvas.height);
          const image = await new Promise<Blob|null>(resolve=>canvas.toBlob(resolve,'image/jpeg',0.85));
          if(!image || image.size > 512*1024)throw Error('Кадр превышает предел обработки');
          const response = await fetch(`${service}/frame?sequence=${sequence}`, {method:'POST',headers:{...headers(),'Content-Type':'image/jpeg'},body:image,signal:AbortSignal.any([request.signal,AbortSignal.timeout(10000)])});
          if(!response.ok)throw Error(`Обработчик вернул ${response.status}`);
          const result: Report = await response.json();
          if(!disposed){setReport(result);setStatus(result.windows ? 'Глубина и камеры обновляются по новым кадрам.' : 'Получен первый кадр. Нужен следующий ракурс.');}
        }
        if(!disposed)timer=setTimeout(()=>{void tick();},1000);
      } catch(error) {
        if(!disposed){setStatus(`3D остановлен: ${error instanceof Error?error.message:'обработчик недоступен'}. Ручной ввод и запись работают отдельно.`);setRunning(false);}
      }
    };
    void(async()=>{
      try {
        if(!element?.requestVideoFrameCallback)throw Error('Браузер не поддерживает наблюдение свежих видеокадров');
        const response = await fetch(`${service}/session`,{method:'POST',headers:{'X-Sphere-Preview':'1','Content-Type':'application/json'},body:JSON.stringify({device_id:deviceId}),signal:AbortSignal.any([request.signal,AbortSignal.timeout(10000)])});
        if(!response.ok)throw Error(`Локальный обработчик не готов (${response.status})`);
        const result: Session = await response.json();
        if(!/^[0-9a-f]{32}$/.test(result.id)||!/^[0-9a-f]{64}$/.test(result.key))throw Error('Некорректная сессия просмотра');
        if(disposed){void fetch(`${service}/stop`,{method:'POST',headers:{'X-Sphere-Preview':'1','X-Scene-Session':result.id,'X-Scene-Key':result.key}}).catch(()=>{});return;}
        session.current=result;setStatus('Ожидаем два свежих ракурса.');observe();void tick();
      } catch(error) {if(!disposed){setStatus(`3D не подключён: ${error instanceof Error?error.message:'ошибка'}. Запустите локальный обработчик по инструкции.`);setRunning(false);}}
    })();
    return()=>{
      disposed=true;request.abort();if(timer)clearTimeout(timer);if(frameCallback!==undefined)element?.cancelVideoFrameCallback(frameCallback);
      if(generation.current===current){const old=session.current;session.current=null;if(old)void fetch(`${service}/stop`,{method:'POST',headers:{'X-Sphere-Preview':'1','X-Scene-Session':old.id,'X-Scene-Key':old.key},keepalive:true}).catch(()=>{});}
      canvas.width=canvas.height=0;
    };
  },[running,deviceId,video]);
  return <section aria-label="Живая 3D-реконструкция" className="overflow-hidden rounded-2xl border border-border bg-card">
    <div className="flex flex-wrap items-start justify-between gap-4 p-4 sm:p-5"><div><h3 className="flex items-center gap-2 text-lg font-semibold"><Box size={20} className="text-primary" />Сцена маршрута · 3D preview</h3><p className="mt-1 max-w-3xl text-sm text-muted-foreground">Depth Anything 3 + Rerun. Реальное облако точек и положение камер из пары ракурсов. Масштаб относительный; каждое окно строится заново, единая карта ещё не сшивается.</p></div>
      <Button variant={running?'secondary':'outline'} disabled={!local||(!running&&(!ready||controlActive))} onClick={()=>{setRunning(v=>!v);if(!running)setReport(null);else setStatus('3D-просмотр остановлен.');}}><RotateCcw size={15} className="mr-2" />{running?'Остановить 3D':'Подключить 3D-просмотр'}</Button></div>
    <div className="flex flex-wrap gap-x-6 gap-y-2 border-y border-border bg-muted/30 px-5 py-3 text-xs"><span role="status">{!local?'Для этой локальной проверки откройте Sphere на компьютере с GPU.':status}</span>{report&&<><span>{report.windows} окон · {report.points.toLocaleString('ru')} точек</span><span>Модель: {report.inference_ms.toFixed(0)} мс · кадр #{report.frame_sequence}</span></>}</div>
    {running?<iframe title="3D-сцена маршрута Rerun" src={viewer} className="h-[600px] w-full border-0 bg-black" sandbox="allow-scripts allow-same-origin allow-downloads" referrerPolicy="no-referrer" allow="fullscreen" />:<div className="flex min-h-40 items-center justify-center p-6 text-center text-sm text-muted-foreground">Здесь появятся точки сцены, исходные ракурсы и камеры. Для геометрии перемещайтесь по миру: неподвижный экран и один поворот камеры не доказывают карту.</div>}
    <p className="px-5 py-3 text-xs leading-5 text-muted-foreground">Сначала подключите 3D и дождитесь сцены, затем включите управление или запись. Обработчик получает до одного уменьшенного кадра в секунду, без очереди и записи кадров на диск. Его частота независима от моторного ИИ. Для объезда препятствий preview пока не используется.</p>
  </section>;
}
