'use client';
import dynamic from 'next/dynamic';
import {useEffect,useRef,useState} from 'react';
import {Box,Loader2} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {reconstructionRequest,terminalReconstruction,uploadReconstruction,type ReconstructionJob,type ReconstructionState} from './reconstructionClient';
const Scene=dynamic(()=>import('./ReconstructedScene'),{ssr:false,loading:()=> <p>Загружаем 3D-просмотр…</p>});
const phases:Record<string,string>={uploading:'Передача сохранённой записи',starting:'Запуск обработчика',verifying:'Проверка исходника и освобождения ввода',extracting:'Извлечение кадров в исходном разрешении',features:'Поиск устойчивых визуальных признаков',matching:'Сопоставление соседних ракурсов',cameras:'Восстановление связанных камер',training:'Построение плотной Gaussian-сцены на GPU',complete:'Плотная сцена готова',failed:'Обработка остановлена',cancelled:'Задание отменено'};
const reasons:Record<string,string>={no_connected_cameras_need_translation_and_overlap:'Не удалось связать камеры. Нужен проход с перемещением, перекрывающимися ракурсами и неподвижными деталями.',camera_quality_gate_failed:'Камеры восстановлены лишь частично или с большой ошибкой. Результат не принят как цельная сцена.',resource_guard:'Недостаточно ресурсов для безопасного продолжения.',worker_service_restarted:'Сервис был перезапущен. Исходная запись сохранена.',brush_failed_see_local_log:'Плотный рендер завершился с ошибкой. Камеры можно проверить отдельно.'};
reasons.brush_timing_overflow='Brush завершился с ошибкой измерения времени GPU. Камеры и проверенные промежуточные результаты сохранены.';
export function TeachingReconstruction({clip,scope,folder,complete,onBusyChange}:{clip:string;scope:string;folder:()=>FileSystemDirectoryHandle|null;complete:boolean;onBusyChange:(busy:boolean)=>void}) {
  const [job,setJob]=useState<ReconstructionJob|null>(null),[status,setStatus]=useState<ReconstructionState|null>(null),[error,setError]=useState<string|null>(null);
  const [mask,setMask]=useState('game'),[steps,setSteps]=useState(5000),[progress,setProgress]=useState('');
  const [uploading,setUploading]=useState(false);const uploadAbort=useRef<AbortController|null>(null);
  const storageKey=`sphere-reconstruction-${scope}-${clip}`;
  const busy=uploading||!!job&&(!status||!terminalReconstruction(status));
  useEffect(()=>{onBusyChange(busy);},[busy,onBusyChange]);
  useEffect(()=>()=>{uploadAbort.current?.abort();onBusyChange(false);},[onBusyChange]);
  useEffect(()=>{try{const saved=JSON.parse(sessionStorage.getItem(storageKey)??'null');if(saved&&/^[0-9a-f]{32}$/.test(saved.id)&&/^[0-9a-f]{64}$/.test(saved.key))setJob(saved);}catch{}},[storageKey]);
  useEffect(()=>{
    if(!job)return;let retired=false;let timer:ReturnType<typeof setTimeout>;const abort=new AbortController();
    const poll=async()=>{try{const next=await(await reconstructionRequest(`/jobs/${job.id}`,job,{signal:abort.signal})).json();if(retired)return;setStatus(next);setError(null);if(!terminalReconstruction(next))timer=setTimeout(()=>{void poll();},2500);}
      catch(e){if(!retired){setError(e instanceof Error&&e.message==='job_not_found'?'Создание задания ещё не подтверждено. Можно продолжить подготовку с тем же идентификатором; обучение повторно не запускается.':`Локальный обработчик не ответил: ${e instanceof Error?e.message:'ошибка'}. Задание не повторялось.`);timer=setTimeout(()=>{void poll();},10000);}}};
    void poll();return()=>{retired=true;abort.abort();clearTimeout(timer);};
  },[job]);
  const start=async()=>{
    const source=folder();if(!source||uploadAbort.current)return;
    const controller=new AbortController();uploadAbort.current=controller;setUploading(true);setError(null);
    let pending:ReconstructionJob|null=job;
    try{
      const next=job??{id:crypto.randomUUID().replaceAll('-',''),key:Array.from(crypto.getRandomValues(new Uint8Array(32)),v=>v.toString(16).padStart(2,'0')).join('')};
      pending=next;sessionStorage.setItem(storageKey,JSON.stringify(next));
      const created=await(await reconstructionRequest('/jobs',null,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...next,mask,steps}),signal:controller.signal})).json();setStatus(created);setJob(next);
      if(created.phase!=='uploading')return;
      await uploadReconstruction(source,next,(bytes,total)=>setProgress(`${(bytes/1048576).toFixed(1)} / ${(total/1048576).toFixed(1)} МБ`),controller.signal);
      const started=await(await reconstructionRequest(`/jobs/${next.id}/start`,next,{method:'POST',body:'{}',signal:controller.signal})).json();setStatus(started);
    }catch(e){if(pending)setJob(pending);setError(`Запуск не подтверждён: ${e instanceof Error?e.message:'нет ответа'}. Проверяем существующее задание; повторного запуска нет.`);}
    finally{uploadAbort.current=null;setUploading(false);}
  };
  const cancel=async()=>{
    uploadAbort.current?.abort();if(!job)return;
    try{setStatus(await(await reconstructionRequest(`/jobs/${job.id}/cancel`,job,{method:'POST',body:'{}'})).json());}catch{setError('Отмена не подтверждена. Состояние проверяется; управление остаётся заблокировано.');}
  };
  return <section aria-label="Построение плотной 3D-сцены" className="space-y-4 rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/5 via-card to-sky-500/5 p-5">
    <div className="flex items-start gap-3"><Box className="mt-1 text-emerald-400" size={24}/><div><h4 className="text-lg font-semibold">Сцена из записанного прохода</h4><p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">После остановки: оригинальные кадры → связанные камеры COLMAP → плотный рендер Brush → просмотр с траекторией. Обработка идёт на этом ПК, отдельно от Android. Первая проверка — 20–60 секунд спокойного прохода.</p></div></div>
    {!status&&<div className="flex flex-wrap items-end gap-4">
      <label className="text-sm">Маска записи<select className="mt-1 block rounded-lg border border-input bg-background p-2" value={mask} onChange={e=>setMask(e.target.value)}><option value="game">HUD и персонаж в центре</option><option value="none">Без маски (чистый кадр)</option></select></label>
      <label className="text-sm">Плотность обработки<select className="mt-1 block rounded-lg border border-input bg-background p-2" value={steps} onChange={e=>setSteps(Number(e.target.value))}><option value={3000}>Проба · 3 000 шагов</option><option value={5000}>Стандарт · 5 000 шагов</option><option value={10000}>Детальнее · 10 000 шагов</option></select></label>
      <Button disabled={!complete||uploading} onClick={()=>{void start();}}>Построить 3D-сцену</Button>
    </div>}
    {status&&<div className="flex flex-wrap items-center gap-3"><p role="status" className="flex items-center gap-2 text-sm font-medium">{busy&&<Loader2 size={16} className="animate-spin"/>}{phases[status.phase]??status.phase}{uploading&&` · ${progress}`}</p>
      {busy&&<Button variant="outline" size="sm" onClick={()=>{void cancel();}}>Отменить обработку</Button>}
      {status.phase==='uploading'&&!uploading&&<Button size="sm" onClick={()=>{void start();}}>Продолжить передачу</Button>}
      {terminalReconstruction(status)&&<Button variant="outline" size="sm" onClick={()=>{sessionStorage.removeItem(storageKey);setJob(null);setStatus(null);setError(null);}}>Новое отдельное задание</Button>}
    </div>}
    {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
    {status?.error&&<p role="alert" className="text-sm text-destructive">{reasons[status.error]??status.error} Исходное видео не изменено.</p>}
    {status?.dense_partial_available&&status.checkpoint&&<p role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">Доступна проверенная промежуточная сцена: {status.checkpoint.steps} / {status.checkpoint.target_steps} итераций. Обработка не завершена успешно; это не окончательный результат.</p>}
    {status?.quality&&<p className="text-xs text-muted-foreground">Камеры {status.quality.registered}/{status.quality.selected} · покрытие {(status.quality.coverage*100).toFixed(0)}% · ошибка {status.quality.mean_reprojection_px.toFixed(2)} px</p>}
    {job&&status?.geometry_available&&<Scene job={job} status={status}/>}
    <p className="text-xs leading-5 text-muted-foreground">Маска применяется до поиска признаков; она не распознаёт все движущиеся машины и игроков. Плотная сцена — визуальная реконструкция, а не готовая карта коллизий. Масштаб в метрах требует отдельного известного расстояния. При нехватке связных ракурсов обработка остановится с объяснением.</p>
  </section>;
}
